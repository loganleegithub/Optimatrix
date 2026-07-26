from __future__ import annotations

from pathlib import Path

import pytest
from conftest import OptionPayloadFactory, PolicyFactory
from radar_runtime.deribit_public import (
    InboundEnvelope,
    PublicProtocolError,
    PublicSessionError,
)
from radar_runtime.runtime import (
    ChannelState,
    FailureScope,
    PendingRpc,
    RadarReducer,
    RpcPurpose,
)
from short_vol_radar.evidence import EvidenceWriter
from short_vol_radar.policy import load_policy_bytes


def make_reducer(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> RadarReducer:
    exact, digest = policy_factory()
    return RadarReducer(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )


def envelope(
    message: dict[str, object],
    *,
    seq: int,
    received_ms: int | None = None,
    epoch: int = 1,
) -> InboundEnvelope:
    return InboundEnvelope(
        {"jsonrpc": "2.0", **message},
        session_epoch=epoch,
        ingress_seq=seq,
        received_monotonic_ms=received_ms if received_ms is not None else 1_000 + seq,
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


def response(
    command: PendingRpc,
    result: object,
    *,
    seq: int,
    received_ms: int | None = None,
) -> InboundEnvelope:
    return envelope(
        {"id": command.request_id, "result": result},
        seq=seq,
        received_ms=received_ms,
        epoch=command.session_epoch,
    )


def begin_through_bootstrap_subscribe(
    reducer: RadarReducer,
) -> tuple[PendingRpc, int]:
    heartbeat = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    commands = reducer.reduce(response(heartbeat, "ok", seq=1), processed_monotonic_ms=1_001)
    subscribe = only(commands, RpcPurpose.SUBSCRIBE_CHANNELS)
    return subscribe, 2


def complete_empty_option_bootstrap(reducer: RadarReducer) -> int:
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    option_catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    reducer.reduce(
        response(clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_000 + seq + 1,
    )
    reducer.reduce(
        response(option_catalog, [], seq=seq + 2),
        processed_monotonic_ms=1_000 + seq + 2,
    )
    return seq + 3


def test_each_accepted_clock_fact_advances_explicit_revision_and_causal_sequence(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    bootstrap = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    causal_before = reducer.causal_seq

    reducer.reduce(
        response(bootstrap, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_000 + seq + 1,
    )
    refresh = reducer._schedule(
        purpose=RpcPurpose.CLOCK_REFRESH,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    reducer.reduce(
        response(refresh, 1_000_001, seq=seq + 2),
        processed_monotonic_ms=1_000 + seq + 2,
    )

    assert reducer.clock_revision == 2
    assert reducer.causal_seq == causal_before + 2


def test_pre_ack_frames_do_not_change_truth_and_reconcile_once_after_ack(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    channel = "instrument.state.option.USDC"
    lifecycle = envelope(
        {
            "method": "subscription",
            "params": {
                "channel": channel,
                "data": {"instrument_name": "CLOSED", "state": "closed"},
            },
        },
        seq=seq,
    )

    assert reducer.reduce(lifecycle, processed_monotonic_ms=1_002) == ()
    assert reducer.channel_state(channel) is ChannelState.SUBSCRIBE_PENDING
    assert reducer.option_catalog.buffered_events == []

    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq + 1),
        processed_monotonic_ms=1_003,
    )

    assert reducer.channel_state(channel) is ChannelState.ACKNOWLEDGED
    assert reducer.option_catalog.buffered_events == [
        {"instrument_name": "CLOSED", "state": "closed"}
    ]
    assert reducer.diagnostics.reduced_envelope_count == 3
    assert reducer.diagnostics.business_apply_count_by_ingress[(1, seq)] == 1


def test_response_then_later_ingress_with_earlier_receive_time_cannot_regress_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(
            subscribe,
            exact_channels(subscribe),
            seq=seq,
            received_ms=2_000,
        ),
        processed_monotonic_ms=2_000,
    )
    status = only(commands, RpcPurpose.PLATFORM_STATUS)
    reducer.reduce(
        response(
            status,
            {"locked": False, "locked_indices": []},
            seq=seq + 1,
            received_ms=2_000,
        ),
        processed_monotonic_ms=2_000,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": "CLOSED", "state": "closed"},
                },
            },
            seq=seq + 2,
            received_ms=1_000,
        ),
        processed_monotonic_ms=2_000,
    )

    assert reducer._current_fact_boundary().received_monotonic_ms == 2_000
    assert reducer._last_inbound_received_ms == 2_000
    assert reducer.diagnostics.business_apply_count_by_ingress[(1, seq + 2)] == 1


def test_retired_channel_generation_frame_has_zero_business_effect(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    channel = "instrument.state.option.USDC"
    reducer._plan_channel_change(
        (channel,),
        subscribe=False,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION_CATALOG,
    )
    unsubscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.UNSUBSCRIBE_CHANNELS)
    reducer.reduce(
        response(unsubscribe, exact_channels(unsubscribe), seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": channel,
                    "data": {"instrument_name": "RETIRED", "state": "open"},
                },
            },
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )

    assert reducer.channel_state(channel) is ChannelState.RETIRED
    assert reducer.option_catalog.buffered_events == []
    assert reducer.diagnostics.business_apply_count_by_ingress[(1, seq + 2)] == 0


def test_every_frame_reduces_once_and_retired_epoch_has_zero_business_effect(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_002,
    )
    before = reducer.business_fingerprint()

    reducer.begin_session(session_epoch=2, monotonic_ms=2_000)
    old = envelope(
        {
            "method": "subscription",
            "params": {
                "channel": "instrument.state.option.USDC",
                "data": {"instrument_name": "OLD", "state": "open"},
            },
        },
        seq=seq + 1,
        epoch=1,
        received_ms=1,
    )
    assert reducer.reduce(old, processed_monotonic_ms=2_001) == ()
    assert reducer.business_fingerprint() != before
    assert "OLD" not in reducer.catalog_options
    assert reducer.diagnostics.retired_epoch_frame_count == 1
    assert reducer.diagnostics.session_gap_count == 1

    current_heartbeat = next(iter(reducer.pending_rpcs.values()))
    reducer.reduce(
        response(current_heartbeat, "ok", seq=1, received_ms=2_001),
        processed_monotonic_ms=2_002,
    )
    with pytest.raises(PublicSessionError, match="ingress"):
        reducer.reduce(
            response(current_heartbeat, "ok", seq=1, received_ms=2_002),
            processed_monotonic_ms=2_003,
        )


def test_success_error_late_notification_and_heartbeat_response_reduce_once(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    status = only(commands, RpcPurpose.PLATFORM_STATUS)
    combo = only(commands, RpcPurpose.COMBO_CATALOG)
    reducer.reduce(
        response(
            status,
            {"locked": False, "locked_indices": [], "locked_currencies": []},
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        envelope(
            {
                "id": combo.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )
    reducer.reduce(
        envelope({"id": 999_999, "result": "late"}, seq=seq + 3),
        processed_monotonic_ms=1_003 + seq,
    )
    heartbeat_command = only(
        reducer.reduce(
            envelope(
                {"method": "heartbeat", "params": {"type": "test_request"}},
                seq=seq + 4,
            ),
            processed_monotonic_ms=1_004 + seq,
        ),
        RpcPurpose.HEARTBEAT_TEST,
    )
    reducer.reduce(
        response(
            heartbeat_command,
            {"version": "2.1.1"},
            seq=seq + 5,
        ),
        processed_monotonic_ms=1_005 + seq,
    )

    assert reducer.diagnostics.reduced_envelope_count == seq + 5
    assert reducer.diagnostics.rpc_success_count["public/status"] == 1
    assert reducer.diagnostics.rpc_error_count["public/get_combos"] == 1
    assert reducer.diagnostics.late_response_count == 1
    assert reducer.diagnostics.heartbeat_public_test_success_count == 1


def test_heartbeat_control_is_live_while_channel_rpc_is_pending(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)

    commands = reducer.reduce(
        envelope(
            {
                "method": "heartbeat",
                "params": {"type": "test_request"},
            },
            seq=seq,
        ),
        processed_monotonic_ms=1_002,
    )

    public_test = only(commands, RpcPurpose.HEARTBEAT_TEST)
    assert public_test.method == "public/test"
    assert public_test.failure_scope is FailureScope.SESSION
    assert subscribe.request_id in reducer.pending_rpcs


@pytest.mark.parametrize("during_bootstrap", [True, False])
def test_one_receive_lag_gate_retires_bootstrap_and_normal_frames(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    during_bootstrap: bool,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    if during_bootstrap:
        heartbeat = only(
            reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
            RpcPurpose.SET_HEARTBEAT,
        )
        delayed = response(heartbeat, "ok", seq=1, received_ms=1_001)
    else:
        subscribe, seq = begin_through_bootstrap_subscribe(reducer)
        reducer.reduce(
            response(subscribe, exact_channels(subscribe), seq=seq),
            processed_monotonic_ms=1_000 + seq,
        )
        delayed = envelope(
            {"method": "heartbeat", "params": {"type": "heartbeat"}},
            seq=seq + 1,
            received_ms=1_000 + seq + 1,
        )

    with pytest.raises(PublicSessionError, match="queue lag"):
        reducer.reduce(
            delayed,
            processed_monotonic_ms=delayed.received_monotonic_ms + 1_001,
        )

    assert reducer.diagnostics.max_receive_to_reduce_lag_ms == 1_001
    assert reducer.diagnostics.session_gap_count == 1


def test_negative_platform_guard_cannot_be_overwritten_in_same_epoch(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_002,
    )
    status = only(commands, RpcPurpose.PLATFORM_STATUS)

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "platform_state",
                    "data": {"maintenance": True},
                },
            },
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_003,
    )
    reducer.reduce(
        response(
            status,
            {"locked": False, "locked_indices": [], "locked_currencies": []},
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_004,
    )

    assert not reducer.platform.usable
    assert reducer.platform.reason == "PLATFORM_MAINTENANCE"


def test_invalid_core_status_shape_is_fatal_protocol_incompatibility(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    status = only(commands, RpcPurpose.PLATFORM_STATUS)

    with pytest.raises(PublicProtocolError, match="public/status"):
        reducer.reduce(
            response(status, {"locked": "unsupported"}, seq=seq + 1),
            processed_monotonic_ms=1_001 + seq,
        )


def test_invalid_option_lifecycle_enters_catalog_recovery_not_session_failure(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": "BROKEN"},
                },
            },
            seq=seq,
            received_ms=2_000,
        ),
        processed_monotonic_ms=2_000,
    )

    assert not reducer.option_catalog.complete
    assert reducer.diagnostics.session_gap_count == 0
    assert reducer._next_option_catalog_recovery_ms is not None


def test_open_close_then_metadata_response_cannot_resurrect_contract(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)
    name = "BTC_USDC-TEST-110000-C"

    commands = reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": "open"},
                },
            },
            seq=seq,
        ),
        processed_monotonic_ms=1_000 + seq,
    )
    metadata = only(commands, RpcPurpose.OPTION_METADATA)
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": "closed"},
                },
            },
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        response(metadata, option_payload_factory(name=name), seq=seq + 2),
        processed_monotonic_ms=1_002 + seq,
    )

    assert name not in reducer.catalog_options


def test_metadata_response_commits_after_sustained_market_ingress(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    existing = "BTC_USDC-TEST-100010-C"
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    dynamic = reducer.reduce(
        response(
            catalog,
            [option_payload_factory(name=existing, strike=100_010)],
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )
    next_seq = seq + 3
    for command in tuple(item for item in dynamic if item.purpose is RpcPurpose.SUBSCRIBE_CHANNELS):
        reducer.reduce(
            response(command, exact_channels(command), seq=next_seq),
            processed_monotonic_ms=1_000 + next_seq,
        )
        next_seq += 1

    metadata = only(
        reducer.reduce(
            envelope(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": name, "state": "open"},
                    },
                },
                seq=next_seq,
            ),
            processed_monotonic_ms=1_000 + next_seq,
        ),
        RpcPurpose.OPTION_METADATA,
    )
    next_seq += 1
    for source_timestamp in range(1, 21):
        reducer.reduce(
            envelope(
                {
                    "method": "subscription",
                    "params": {
                        "channel": f"ticker.{existing}.100ms",
                        "data": {
                            "instrument_name": existing,
                            "timestamp": source_timestamp,
                            "underlying_price": 100_000,
                            "underlying_index": "BTC_USDC-TEST",
                        },
                    },
                },
                seq=next_seq,
            ),
            processed_monotonic_ms=1_000 + next_seq,
        )
        next_seq += 1

    reducer.reduce(
        response(metadata, option_payload_factory(name=name), seq=next_seq),
        processed_monotonic_ms=1_000 + next_seq,
    )

    assert name in reducer.catalog_options
    assert reducer.diagnostics.channel_received_count["OPTION_TICKER"] == 20


def test_close_while_option_snapshot_is_pending_wins_over_old_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": "closed"},
                },
            },
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        response(
            catalog,
            [option_payload_factory(name=name)],
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )

    assert name not in reducer.catalog_options
    assert not any(
        request.purpose is RpcPurpose.OPTION_METADATA and request.scope == name
        for request in reducer.pending_rpcs.values()
    )


def test_heartbeat_is_live_while_unsubscribe_ack_is_blocked(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    channel = "instrument.state.option.USDC"
    reducer._plan_channel_change(
        (channel,),
        subscribe=False,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION_CATALOG,
    )
    unsubscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.UNSUBSCRIBE_CHANNELS)

    commands = reducer.reduce(
        envelope(
            {"method": "heartbeat", "params": {"type": "test_request"}},
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_001 + seq,
    )

    assert only(commands, RpcPurpose.HEARTBEAT_TEST).method == "public/test"
    assert unsubscribe.request_id in reducer.pending_rpcs
    assert reducer.channel_state(channel) is ChannelState.UNSUBSCRIBE_PENDING


def test_combo_burst_during_refresh_produces_one_authoritative_trailing_refresh(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    first = only(commands, RpcPurpose.COMBO_CATALOG)

    for current_seq in range(seq + 1, seq + 6):
        assert (
            reducer.reduce(
                envelope(
                    {
                        "method": "subscription",
                        "params": {
                            "channel": "instrument.state.option_combo.USDC",
                            "data": {
                                "instrument_name": f"COMBO-{current_seq}",
                                "state": "open",
                            },
                        },
                    },
                    seq=current_seq,
                ),
                processed_monotonic_ms=1_000 + current_seq,
            )
            == ()
        )

    trailing = reducer.reduce(
        response(first, [], seq=seq + 6),
        processed_monotonic_ms=1_000 + seq + 6,
    )
    second = only(trailing, RpcPurpose.COMBO_CATALOG)
    assert first.generation is not None
    assert second.generation == first.generation + 1

    for current_seq in range(seq + 7, seq + 10):
        reducer.reduce(
            envelope(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option_combo.USDC",
                        "data": {
                            "instrument_name": f"TRAILING-{current_seq}",
                            "state": "closed",
                        },
                    },
                },
                seq=current_seq,
            ),
            processed_monotonic_ms=1_000 + current_seq,
        )
    assert (
        reducer.reduce(
            response(second, [], seq=seq + 10),
            processed_monotonic_ms=1_000 + seq + 10,
        )
        == ()
    )
    assert reducer.diagnostics.combo_authoritative_refresh_attempt_count == 2


def test_nonempty_combo_catalog_fetches_metadata_once_and_reuses_unchanged(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    catalog = only(commands, RpcPurpose.COMBO_CATALOG)
    summary = {
        "id": "COMBO",
        "state": "active",
        "legs": [
            {"instrument_name": "SHORT", "amount": -1},
            {"instrument_name": "LONG", "amount": 1},
        ],
    }

    metadata_commands = reducer.reduce(
        response(catalog, [summary], seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    metadata = only(metadata_commands, RpcPurpose.COMBO_METADATA)
    reducer.reduce(
        response(
            metadata,
            {
                "instrument_name": "COMBO",
                "kind": "option_combo",
                "base_currency": "BTC",
                "quote_currency": "USDC",
                "settlement_currency": "USDC",
                "counter_currency": "USDC",
                "instrument_type": "linear",
                "contract_size": 1,
                "min_trade_amount": 0.1,
                "qty_tick_size": 0.1,
            },
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )
    assert tuple(reducer.combos) == ("COMBO",)
    assert reducer.combo_catalog.complete

    refresh = reducer._schedule_combo_refresh(
        reducer._current_fact_boundary(),
        trailing=False,
    )
    assert (
        reducer.reduce(
            response(refresh, [summary], seq=seq + 3),
            processed_monotonic_ms=1_003 + seq,
        )
        == ()
    )
    assert tuple(reducer.combos) == ("COMBO",)


def test_operational_recovery_and_subscription_peaks_are_runtime_facts(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    initial_channel_peak = reducer.diagnostics.peak_subscribed_channel_count
    assert initial_channel_peak == len(exact_channels(subscribe))

    reducer.prepare_reconnect("TEST_SESSION_GAP")
    reducer.prepare_reconnect("DUPLICATE_NOTICE")
    reducer.begin_session(session_epoch=2, monotonic_ms=2_000)

    assert reducer.diagnostics.session_gap_count == 1
    assert reducer.diagnostics.reconnect_count == 1
    assert reducer.diagnostics.peak_subscribed_channel_count == initial_channel_peak


def test_live_transport_metrics_feed_strict_operational_diagnostics(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)

    reducer.note_transport_metrics(queue_high_water_frames=7, overflow_count=2)
    reducer.note_transport_metrics(queue_high_water_frames=4, overflow_count=2)

    diagnostics = reducer._operational_diagnostics(1_000)
    ingress = diagnostics["ingress"]
    assert isinstance(ingress, dict)
    assert ingress["queue_high_water_frames"] == 7
    assert ingress["overflow_count"] == 2


def test_source_shape_diagnostics_keep_only_consumed_keys_and_types(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)

    reducer._note_source_shape(
        "public/get_instrument",
        {
            "instrument_name": "OPTION",
            "kind": "option",
            "expiration_timestamp": 1_000,
            "unrelated_future_field": {"market": "payload"},
        },
        valid=True,
    )

    diagnostics = reducer._operational_diagnostics(1_000)
    rows = diagnostics["source_shapes"]
    assert isinstance(rows, list)
    row = next(item for item in rows if item["source"] == "public/get_instrument")
    assert row["consumed_fields"] == [
        {"key": "expiration_timestamp", "type": "integer"},
        {"key": "instrument_name", "type": "string"},
        {"key": "kind", "type": "string"},
    ]


def test_incomplete_catalog_response_is_rpc_success_but_shape_invalid(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)

    reducer.reduce(
        response(
            catalog,
            [{"instrument_name": "BROKEN"}],
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_001 + seq,
    )

    assert reducer.diagnostics.rpc_success_count["public/get_instruments"] == 1
    assert reducer.diagnostics.source_valid_count["public/get_instruments"] == 0
    assert reducer.diagnostics.source_invalid_count["public/get_instruments"] == 1
    assert not reducer.option_catalog.complete
    recovery = reducer._operational_diagnostics(1_000)["recovery"]
    assert isinstance(recovery, dict)
    assert recovery["option_catalog_refresh_success_count"] == 0
    assert recovery["option_catalog_refresh_failure_count"] == 1


def test_incomplete_option_snapshot_cannot_create_membership_loss(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        response(
            catalog,
            [option_payload_factory(name=name)],
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )
    assert name in reducer.catalog_options

    recovery = reducer._schedule_option_catalog_refresh(reducer._current_fact_boundary())
    reducer.reduce(
        response(
            recovery,
            {"not": "an array"},
            seq=seq + 3,
        ),
        processed_monotonic_ms=1_003 + seq,
    )

    assert name in reducer.catalog_options
    assert name in reducer.options
    assert not reducer.option_catalog.complete


def test_incomplete_catalogs_recover_once_at_policy_derived_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    reducer.option_catalog.acknowledge_lifecycle()
    reducer.option_catalog.reconcile()
    reducer.combo_catalog.acknowledge_lifecycle()
    reducer.combo_catalog.reconcile()
    reducer.option_catalog.mark_incomplete()
    reducer.combo_catalog.mark_incomplete()
    reducer._next_option_catalog_recovery_ms = 2_000
    reducer._next_combo_catalog_recovery_ms = 2_000

    assert reducer.advance_time(1_999) == ()
    commands = reducer.advance_time(2_000)

    assert (
        len(tuple(command for command in commands if command.purpose is RpcPurpose.OPTION_CATALOG))
        == 1
    )
    assert (
        len(tuple(command for command in commands if command.purpose is RpcPurpose.COMBO_CATALOG))
        == 1
    )
    assert reducer.advance_time(2_001) == ()


def test_lifecycle_during_option_catalog_recovery_wins_over_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)
    name = "BTC_USDC-TEST-110000-C"
    reducer.option_catalog.mark_incomplete()
    reducer._next_option_catalog_recovery_ms = 2_000

    recovery = only(reducer.advance_time(2_000), RpcPurpose.OPTION_CATALOG)
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": "closed"},
                },
            },
            seq=seq,
            received_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )
    reducer.reduce(
        response(
            recovery,
            [option_payload_factory(name=name)],
            seq=seq + 1,
            received_ms=2_002,
        ),
        processed_monotonic_ms=2_002,
    )

    assert name not in reducer.catalog_options
    assert reducer.option_catalog.complete
