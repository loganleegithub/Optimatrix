from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import MethodType

import pytest
import radar_runtime.runtime as runtime_module
from conftest import OptionPayloadFactory, PolicyFactory
from market_monitor import ContinuousOrderBook, TrustedClock
from options_domain import AmountMetadata, OptionInstrument, OptionType
from radar_runtime.deribit_public import (
    InboundEnvelope,
    PublicProtocolError,
    PublicSessionError,
)
from radar_runtime.runtime import (
    ChannelState,
    FactBoundary,
    FailureScope,
    PendingRpc,
    RadarReducer,
    RpcPurpose,
)
from short_vol_radar.detector import DetectorState, EpisodeTracker
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


def _option_for_combo_test(
    name: str,
    strike: int,
    *,
    expiry_ms: int = 2_000_000,
) -> OptionInstrument:
    return OptionInstrument(
        instrument_name=name,
        expiration_timestamp_ms=expiry_ms,
        strike=Decimal(strike),
        option_type=OptionType.CALL,
        amount=AmountMetadata(
            contract_size=Decimal(1),
            min_trade_amount=Decimal("0.1"),
            qty_tick_size=Decimal("0.1"),
        ),
    )


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


def accept_platform_status(
    reducer: RadarReducer,
    commands: tuple[PendingRpc, ...],
    *,
    seq: int,
) -> tuple[tuple[PendingRpc, ...], int]:
    status = only(commands, RpcPurpose.PLATFORM_STATUS)
    commands = reducer.reduce(
        response(
            status,
            {"locked": False, "locked_indices": [], "locked_currencies": []},
            seq=seq,
        ),
        processed_monotonic_ms=1_000 + seq,
    )
    return commands, seq


def complete_empty_option_bootstrap(reducer: RadarReducer) -> int:
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
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


def test_clock_refresh_preserves_established_index_generation_and_history(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    reducer.clock = TrustedClock.from_response(
        1_020_000,
        1_000,
        1_000,
        stale_deadline_ms=60_000,
    )
    reducer._plan_channel_change(
        ("deribit_price_index.btc_usdc",),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)
    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=1, received_ms=1_001),
        processed_monotonic_ms=1_001,
    )
    reducer.index.start_continuous_coverage(600_000)
    for causal_seq, timestamp in enumerate(
        (600_001, 660_000, 720_000, 780_000, 840_000, 900_000, 960_000, 1_020_000),
        start=1,
    ):
        reducer.index.accept_tick(
            source_timestamp_ms=timestamp,
            price=100 + causal_seq,
            causal_seq=causal_seq,
        )
        reducer.index.seal_ready(timestamp)
    sealed_before = reducer.index.sealed
    generation_before = reducer._index_coverage_generation
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
        response(refresh, 1_020_010, seq=2, received_ms=1_010),
        processed_monotonic_ms=1_010,
    )

    assert reducer.index.sealed == sealed_before
    assert reducer.index.has_accepted_tick
    assert reducer._index_coverage_generation == generation_before


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


def test_reordered_subscription_ack_commits_the_requested_batch(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    requested = exact_channels(subscribe)

    commands = reducer.reduce(
        response(subscribe, list(reversed(requested)), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )

    assert all(reducer.channel_state(channel) is ChannelState.ACKNOWLEDGED for channel in requested)
    assert only(commands, RpcPurpose.PLATFORM_STATUS)


def test_partial_bootstrap_subscription_ack_is_a_session_failure(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    requested = exact_channels(subscribe)
    applied: list[int] = []
    monkeypatch.setattr(
        reducer,
        "_apply_acknowledged_subscription",
        lambda current, **_kwargs: applied.append(current.ingress_seq),
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": requested[0], "data": {}},
            },
            seq=seq,
        ),
        processed_monotonic_ms=1_000 + seq,
    )

    with pytest.raises(PublicSessionError, match="SUBSCRIBE_CHANNELS"):
        reducer.reduce(
            response(subscribe, requested[:-1], seq=seq + 1),
            processed_monotonic_ms=1_000 + seq + 1,
        )
    assert applied == []
    assert reducer._held_subscription_frame_count == 0
    assert reducer.diagnostics.rpc_success_count["public/subscribe"] == 0
    assert reducer.diagnostics.rpc_error_count["public/subscribe"] == 1
    assert reducer.diagnostics.source_valid_count["public/subscribe"] == 1
    assert reducer.diagnostics.source_invalid_count["public/subscribe"] == 0


def test_partial_channel_ack_commits_missing_truth_before_releasing_success_frame(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    first = "ticker.FIRST.100ms"
    second = "ticker.SECOND.100ms"
    reducer.options = {
        name: _option_for_combo_test(name, strike)
        for name, strike in (("FIRST", 100), ("SECOND", 110))
    }
    reducer._plan_channel_change(
        (first, second),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": first, "data": {}},
            },
            seq=1,
        ),
        processed_monotonic_ms=1_001,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": second, "data": {}},
            },
            seq=2,
        ),
        processed_monotonic_ms=1_002,
    )
    applied: list[int] = []

    def assert_atomic_release(
        current: InboundEnvelope,
        **_kwargs: object,
    ) -> None:
        assert reducer.channel_state(second) is ChannelState.RETIRED
        assert reducer._channels[second].retry_after_ms is not None
        assert reducer._ticker_unavailable["SECOND"] == (
            "OPTION_CHANNEL_FAILURE",
            True,
        )
        applied.append(current.ingress_seq)

    monkeypatch.setattr(
        reducer,
        "_apply_acknowledged_subscription",
        assert_atomic_release,
    )

    reducer.reduce(
        response(subscribe, [first], seq=3),
        processed_monotonic_ms=1_003,
    )

    assert applied == [1]
    assert reducer._held_subscription_frame_count == 0


def test_partial_channel_ack_commits_successes_and_scopes_missing_failure(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    first = "ticker.FIRST.100ms"
    second = "ticker.SECOND.100ms"
    reducer._plan_channel_change(
        (first, second),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)

    reducer.reduce(
        response(subscribe, [first], seq=1),
        processed_monotonic_ms=1_001,
    )

    assert reducer.channel_state(first) is ChannelState.ACKNOWLEDGED
    assert reducer.channel_state(second) is ChannelState.RETIRED
    assert reducer._channels[second].retry_after_ms is not None
    assert reducer.diagnostics.rpc_success_count["public/subscribe"] == 0
    assert reducer.diagnostics.rpc_error_count["public/subscribe"] == 1
    assert reducer.diagnostics.source_valid_count["public/subscribe"] == 1
    assert reducer.diagnostics.source_invalid_count["public/subscribe"] == 0

    reducer._channels[first].desired_subscribed = False
    reducer._channels[second].state = ChannelState.ACKNOWLEDGED
    reducer._channels[second].desired_subscribed = False
    reducer._channels[second].retry_after_ms = None
    reducer._issue_channel_change(
        (first, second),
        subscribe=False,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION,
    )
    unsubscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.UNSUBSCRIBE_CHANNELS)

    reducer.reduce(
        response(unsubscribe, [second], seq=2),
        processed_monotonic_ms=1_002,
    )

    assert reducer.channel_state(second) is ChannelState.RETIRED
    assert reducer.channel_state(first) is ChannelState.ACKNOWLEDGED
    assert reducer._channels[first].retry_after_ms is not None
    assert reducer.diagnostics.rpc_success_count["public/unsubscribe"] == 0
    assert reducer.diagnostics.rpc_error_count["public/unsubscribe"] == 1
    assert reducer.diagnostics.source_valid_count["public/unsubscribe"] == 1
    assert reducer.diagnostics.source_invalid_count["public/unsubscribe"] == 0


def test_partial_ack_does_not_fail_a_channel_owned_by_a_newer_generation(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    first = "ticker.FIRST.100ms"
    second = "ticker.SECOND.100ms"
    third = "ticker.THIRD.100ms"
    reducer._plan_channel_change(
        (first, second, third),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)
    assert subscribe.generation is not None
    newer_generation = subscribe.generation + 1
    reducer._channels[second].generation = newer_generation
    reducer._channels[second].state = ChannelState.SUBSCRIBE_PENDING

    reducer.reduce(
        response(subscribe, [second, first], seq=1),
        processed_monotonic_ms=1_001,
    )

    assert reducer.channel_state(first) is ChannelState.ACKNOWLEDGED
    assert reducer.channel_state(second) is ChannelState.SUBSCRIBE_PENDING
    assert reducer._channels[second].generation == newer_generation
    assert reducer._channels[second].retry_after_ms is None
    assert reducer.channel_state(third) is ChannelState.RETIRED
    assert reducer._channels[third].retry_after_ms is not None


def test_tainted_pending_generation_is_dropped_at_ack_before_resubscribe(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    channel = "ticker.SHORT.100ms"
    reducer._plan_channel_change(
        (channel,),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)
    applied: list[int] = []
    monkeypatch.setattr(
        reducer,
        "_apply_acknowledged_subscription",
        lambda current, **_kwargs: applied.append(current.ingress_seq),
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": channel, "data": {}},
            },
            seq=1,
        ),
        processed_monotonic_ms=1_001,
    )
    reducer._channels[channel].resync_requested = True

    commands = reducer.reduce(
        response(subscribe, [channel], seq=2),
        processed_monotonic_ms=1_002,
    )

    assert applied == []
    assert reducer._held_subscription_frame_count == 0
    assert reducer.channel_state(channel) is ChannelState.UNSUBSCRIBE_PENDING
    assert only(commands, RpcPurpose.UNSUBSCRIBE_CHANNELS).params["channels"] == [channel]


def test_failed_intentional_unsubscribe_does_not_reopen_frame_admission(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    channel = "ticker.REMOVED.100ms"
    reducer._channels[channel] = runtime_module._ChannelSlot(
        state=ChannelState.ACKNOWLEDGED,
        generation=1,
        desired_subscribed=True,
    )
    reducer._next_channel_generation = 2
    reducer._plan_channel_change(
        (channel,),
        subscribe=False,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION_CATALOG,
    )
    unsubscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.UNSUBSCRIBE_CHANNELS)
    reducer.reduce(
        envelope(
            {
                "id": unsubscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            seq=1,
        ),
        processed_monotonic_ms=1_001,
    )
    assert reducer.channel_state(channel) is ChannelState.ACKNOWLEDGED
    assert not reducer._channels[channel].desired_subscribed
    applied: list[int] = []
    monkeypatch.setattr(
        reducer,
        "_apply_acknowledged_subscription",
        lambda current, **_kwargs: applied.append(current.ingress_seq),
    )

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": channel, "data": {}},
            },
            seq=2,
        ),
        processed_monotonic_ms=1_002,
    )

    assert applied == []


def test_removed_option_unsubscribe_failure_does_not_restore_current_result(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    reducer.trackers["REMOVED"] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name="REMOVED",
    )
    channel = "book.REMOVED.100ms"
    reducer._channels[channel] = runtime_module._ChannelSlot(
        state=ChannelState.ACKNOWLEDGED,
        generation=1,
        desired_subscribed=True,
    )
    reducer._next_channel_generation = 2
    reducer._plan_channel_change(
        (channel,),
        subscribe=False,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.OPTION,
    )
    unsubscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.UNSUBSCRIBE_CHANNELS)

    reducer.reduce(
        envelope(
            {
                "id": unsubscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            seq=1,
        ),
        processed_monotonic_ms=1_001,
    )

    assert "REMOVED" not in reducer.results
    assert "REMOVED" not in reducer._ticker_unavailable


def test_pre_ack_frames_from_one_batch_replay_in_global_ingress_order(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    _bootstrap, seq = begin_through_bootstrap_subscribe(reducer)
    reducer._plan_channel_change(
        ("alpha", "beta"),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
    )
    request = next(
        command
        for command in reducer.pending_rpcs.values()
        if command.params.get("channels") == ["alpha", "beta"]
    )
    applied: list[int] = []
    original = reducer._apply_acknowledged_subscription

    def record(
        self: RadarReducer,
        current: InboundEnvelope,
        *,
        commit_boundary: FactBoundary | None = None,
    ) -> None:
        del self
        applied.append(current.ingress_seq)
        original(current, commit_boundary=commit_boundary)

    monkeypatch.setattr(
        reducer,
        "_apply_acknowledged_subscription",
        MethodType(record, reducer),
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": "beta", "data": {}},
            },
            seq=seq,
        ),
        processed_monotonic_ms=1_000 + seq,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": "alpha", "data": {}},
            },
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_001 + seq,
    )

    reducer.reduce(
        response(request, ["alpha", "beta"], seq=seq + 2),
        processed_monotonic_ms=1_002 + seq,
    )

    assert applied == [seq, seq + 1]


def test_pre_ack_frames_from_different_batches_release_at_own_ack_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    channels = tuple(f"channel-{index}" for index in range(101))
    reducer._plan_channel_change(
        channels,
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
    )
    requests = tuple(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    assert len(requests) == 2
    first, second = requests
    first_channel = exact_channels(first)[0]
    second_channel = exact_channels(second)[0]
    applied: list[int] = []
    original = reducer._apply_acknowledged_subscription

    def record(
        self: RadarReducer,
        current: InboundEnvelope,
        *,
        commit_boundary: FactBoundary | None = None,
    ) -> None:
        del self
        applied.append(current.ingress_seq)
        original(current, commit_boundary=commit_boundary)

    monkeypatch.setattr(
        reducer,
        "_apply_acknowledged_subscription",
        MethodType(record, reducer),
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": second_channel, "data": {}},
            },
            seq=1,
        ),
        processed_monotonic_ms=1_001,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": first_channel, "data": {}},
            },
            seq=2,
        ),
        processed_monotonic_ms=1_002,
    )
    reducer.reduce(
        response(first, exact_channels(first), seq=3),
        processed_monotonic_ms=1_003,
    )
    assert applied == [2]

    reducer.reduce(
        response(second, exact_channels(second), seq=4),
        processed_monotonic_ms=1_004,
    )

    assert applied == [2, 1]


def test_pending_channel_does_not_block_acknowledged_channel_fact(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    reducer._plan_channel_change(
        ("acknowledged",),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
    )
    acknowledged = only(
        tuple(reducer.pending_rpcs.values()),
        RpcPurpose.SUBSCRIBE_CHANNELS,
    )
    reducer.reduce(
        response(acknowledged, ["acknowledged"], seq=1),
        processed_monotonic_ms=1_001,
    )
    reducer._plan_channel_change(
        ("pending",),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
    )
    pending = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    applied: list[int] = []
    original = reducer._apply_acknowledged_subscription

    def record(
        self: RadarReducer,
        current: InboundEnvelope,
        *,
        commit_boundary: FactBoundary | None = None,
    ) -> None:
        del self
        applied.append(current.ingress_seq)
        original(current, commit_boundary=commit_boundary)

    monkeypatch.setattr(
        reducer,
        "_apply_acknowledged_subscription",
        MethodType(record, reducer),
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": "pending", "data": {}},
            },
            seq=2,
        ),
        processed_monotonic_ms=1_002,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {"channel": "acknowledged", "data": {}},
            },
            seq=3,
        ),
        processed_monotonic_ms=1_003,
    )

    assert applied == [3]
    reducer.reduce(
        response(pending, ["pending"], seq=4),
        processed_monotonic_ms=1_004,
    )
    assert applied == [3, 2]


def test_index_ack_then_clock_failure_still_releases_held_tick_once_on_recovery(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    reducer._plan_channel_change(
        ("deribit_price_index.btc_usdc",),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)
    applied: list[tuple[int, int]] = []
    settled_causal: list[int] = []
    original_apply_index = reducer._apply_index
    original_settle = reducer._settle_fact

    def record_index(
        payload: object,
        boundary: FactBoundary,
    ) -> bool:
        applied.append((boundary.ingress_seq, boundary.causal_seq))
        return original_apply_index(payload, boundary)

    def record_settle(**kwargs: object) -> None:
        boundary = kwargs["boundary"]
        assert isinstance(boundary, FactBoundary)
        settled_causal.append(boundary.causal_seq)
        original_settle(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reducer, "_apply_index", record_index)
    monkeypatch.setattr(reducer, "_settle_fact", record_settle)

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "deribit_price_index.btc_usdc",
                    "data": {
                        "timestamp": 660_010,
                        "price": 100,
                        "index_name": "btc_usdc",
                    },
                },
            },
            seq=1,
            received_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )
    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=2, received_ms=1_002),
        processed_monotonic_ms=1_002,
    )
    assert applied == []
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "deribit_price_index.btc_usdc",
                    "data": {
                        "timestamp": 660_020,
                        "price": 200,
                        "index_name": "btc_usdc",
                    },
                },
            },
            seq=3,
            received_ms=1_003,
        ),
        processed_monotonic_ms=1_003,
    )
    assert applied == []
    assert reducer._held_subscription_frame_count == 2

    first_clock = reducer._schedule(
        purpose=RpcPurpose.CLOCK_BOOTSTRAP,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    reducer.reduce(
        envelope(
            {
                "id": first_clock.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            seq=4,
            received_ms=1_004,
        ),
        processed_monotonic_ms=1_004,
    )
    assert applied == []

    recovered_clock = reducer._schedule(
        purpose=RpcPurpose.CLOCK_BOOTSTRAP,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    reducer.reduce(
        response(recovered_clock, 660_000, seq=5, received_ms=1_005),
        processed_monotonic_ms=1_005,
    )

    assert len(applied) == 2
    assert [ingress_seq for ingress_seq, _causal_seq in applied] == [5, 5]
    assert reducer._held_subscription_frame_count == 0
    assert reducer.index.has_accepted_tick
    assert reducer.index._last_source_timestamp_ms == 660_020
    assert reducer.index._working[660_000].price == Decimal(200)
    assert settled_causal == sorted(settled_causal)
    assert settled_causal[-1] > settled_causal[-2]


def test_index_coverage_starts_at_trusted_upper_bound(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    reducer.clock = TrustedClock.from_response(
        59_999,
        1_000,
        1_050,
        stale_deadline_ms=60_000,
    )
    reducer._plan_channel_change(
        ("deribit_price_index.btc_usdc",),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)

    reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=1, received_ms=1_050),
        processed_monotonic_ms=1_050,
    )
    reducer.index.accept_tick(
        source_timestamp_ms=60_010,
        price=100,
        causal_seq=1,
    )
    reducer.index.accept_tick(
        source_timestamp_ms=120_000,
        price=101,
        causal_seq=2,
    )
    reducer.index.seal_ready(120_000)

    assert all(close.minute_start_ms != 60_000 for close in reducer.index.sealed)


def test_pre_ack_frame_holding_is_globally_bounded_and_fails_session_closed(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    _subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    monkeypatch.setattr(runtime_module, "MAX_PENDING_INBOUND_FRAMES", 1)
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": "OPTION", "state": "open"},
                },
            },
            seq=seq,
        ),
        processed_monotonic_ms=1_000 + seq,
    )

    with pytest.raises(PublicSessionError, match=r"pre-ack.*overflow"):
        reducer.reduce(
            envelope(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option_combo.USDC",
                        "data": {"instrument_name": "COMBO", "state": "open"},
                    },
                },
                seq=seq + 1,
            ),
            processed_monotonic_ms=1_001 + seq,
        )

    assert reducer.diagnostics.session_gap_count == 1
    assert reducer._held_subscription_frame_count == 0


def test_subscription_changes_are_split_into_exact_bounded_batches(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    channels = tuple(f"channel-{index}" for index in range(205))

    reducer._plan_channel_change(
        channels,
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
    )
    requests = tuple(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )

    assert [len(exact_channels(request)) for request in requests] == [100, 100, 5]
    assert [channel for request in requests for channel in exact_channels(request)] == list(
        channels
    )
    assert len({request.generation for request in requests}) == 3


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
    assert reducer.diagnostics.source_observed_count["option_lifecycle"] == 1


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
    assert reducer.diagnostics.source_observed_count["option_lifecycle"] == 0


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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    combo = only(commands, RpcPurpose.COMBO_CATALOG)
    reducer.reduce(
        envelope(
            {
                "id": combo.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            seq=seq + 1,
        ),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        envelope({"id": 999_999, "result": "late"}, seq=seq + 2),
        processed_monotonic_ms=1_002 + seq,
    )
    heartbeat_command = only(
        reducer.reduce(
            envelope(
                {"method": "heartbeat", "params": {"type": "test_request"}},
                seq=seq + 3,
            ),
            processed_monotonic_ms=1_003 + seq,
        ),
        RpcPurpose.HEARTBEAT_TEST,
    )
    reducer.reduce(
        response(
            heartbeat_command,
            {"version": "2.1.1"},
            seq=seq + 4,
        ),
        processed_monotonic_ms=1_004 + seq,
    )

    assert reducer.diagnostics.reduced_envelope_count == seq + 4
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
    assert reducer.diagnostics.global_continuity_restart_count == {"QUEUE_LAG_DEADLINE": 1}


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

    with pytest.raises(PublicSessionError, match="platform guard"):
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


def test_heartbeat_success_cannot_satisfy_post_status_business_probe(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    reducer.platform.apply_status({"locked": False})
    reducer.platform.apply_platform_notification({"maintenance": False})
    reducer.platform.apply_public_methods_notification(
        {"allow_unauthenticated_public_requests": True}
    )
    reducer._last_ingress_seq = 5
    reducer._platform_status_ingress_seq = 5
    old_request = reducer._schedule(
        purpose=RpcPurpose.HEARTBEAT_TEST,
        method="public/test",
        params={},
        scope="SESSION_CONTROL",
        generation=None,
        origin_boundary=runtime_module.FactBoundary(1, 4, 1_004, 1),
        failure_scope=FailureScope.SESSION,
    )

    reducer.reduce(
        response(old_request, {"version": "1"}, seq=6),
        processed_monotonic_ms=1_006,
    )
    assert not reducer.platform.post_status_probe

    new_request = reducer._schedule(
        purpose=RpcPurpose.HEARTBEAT_TEST,
        method="public/test",
        params={},
        scope="SESSION_CONTROL",
        generation=None,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.SESSION,
    )
    reducer.reduce(
        response(new_request, {"version": "1"}, seq=7),
        processed_monotonic_ms=1_007,
    )

    assert not reducer.platform.post_status_probe


def test_final_post_status_success_recomputes_current_truth_in_same_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    reducer.clock = TrustedClock.from_response(
        1_000_000,
        1_000,
        1_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.index.start_continuous_coverage(900_000)
    reducer.index.accept_tick(
        source_timestamp_ms=1_000_000,
        price=100,
        causal_seq=1,
    )
    reducer.platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    reducer.platform.apply_status({"locked": False})
    reducer.platform.apply_platform_notification({"maintenance": False})
    reducer.platform.apply_public_methods_notification(
        {"allow_unauthenticated_public_requests": True}
    )
    reducer.platform.note_fresh_index_coverage()
    reducer._platform_status_ingress_seq = 1
    reducer._last_ingress_seq = 1
    reducer.option_catalog.complete = True
    reducer.option_catalog.source_complete = True
    reducer.combo_catalog.source_complete = True
    instrument = _option_for_combo_test("SHORT", 100, expiry_ms=4_600_000)
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[instrument.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=instrument.instrument_name,
    )
    book = ContinuousOrderBook(instrument.instrument_name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1_000_000,
            "instrument_name": instrument.instrument_name,
            "change_id": 1,
            "bids": [],
            "asks": [],
        },
        1_000,
    )
    reducer.option_books[instrument.instrument_name] = book
    reducer._settle_fact(
        boundary=FactBoundary(1, 1, 1_000, 1),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
        observation_reason="PLATFORM_UNESTABLISHED",
    )
    assert reducer.trackers[instrument.instrument_name].detector_state is DetectorState.UNKNOWN

    requests = tuple(
        reducer._schedule(
            purpose=purpose,
            method={
                RpcPurpose.CLOCK_BOOTSTRAP: "public/get_time",
                RpcPurpose.OPTION_CATALOG: "public/get_instruments",
                RpcPurpose.COMBO_CATALOG: "public/get_combos",
            }[purpose],
            params={},
            scope=purpose.value,
            generation=None,
            origin_boundary=FactBoundary(1, 1, 1_000, 1),
            failure_scope=FailureScope.CLOCK_INDEX,
        )
        for purpose in (
            RpcPurpose.CLOCK_BOOTSTRAP,
            RpcPurpose.OPTION_CATALOG,
            RpcPurpose.COMBO_CATALOG,
        )
    )
    for causal_seq, request in enumerate(requests, start=2):
        reducer._note_post_status_bootstrap_success(
            request,
            source_valid=True,
            boundary=FactBoundary(1, causal_seq, 1_000 + causal_seq, causal_seq),
        )

    assert reducer.platform.usable
    assert reducer.trackers[instrument.instrument_name].detector_state is DetectorState.NO_ANOMALY
    assert reducer.results[instrument.instrument_name].known_evaluation
    assert reducer.aggregate_results
    assert all(
        aggregate.state is DetectorState.NO_ANOMALY
        for aggregate in reducer.aggregate_results.values()
    )


def test_boolean_response_id_is_fatal_protocol_incompatibility(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)

    with pytest.raises(PublicProtocolError, match="response id"):
        reducer.reduce(
            envelope({"id": True, "result": "ok"}, seq=1),
            processed_monotonic_ms=1_001,
        )


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


@pytest.mark.parametrize(
    "status",
    [
        {"locked": True},
        {"locked": "partial", "locked_indices": ["btc_usdc"]},
    ],
)
def test_relevant_platform_lock_status_fails_epoch_canonically(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    status: dict[str, object],
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    request = only(commands, RpcPurpose.PLATFORM_STATUS)

    with pytest.raises(PublicSessionError, match="RELEVANT_PLATFORM_LOCK"):
        reducer.reduce(
            response(request, status, seq=seq + 1),
            processed_monotonic_ms=1_001 + seq,
        )

    assert not reducer.platform.usable
    assert reducer.platform.reason == "RELEVANT_PLATFORM_LOCK"
    assert reducer.diagnostics.session_gap_count == 1
    assert reducer.pending_rpcs == {}


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
                    "data": {"instrument_name": name, "state": "inactive"},
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


def test_open_option_is_catalog_incomplete_until_matching_metadata_commits(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)
    name = "BTC_USDC-TEST-110000-C"
    assert reducer.option_catalog.complete

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

    assert not reducer.option_catalog.complete
    reducer.reduce(
        response(metadata, option_payload_factory(name=name), seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )

    assert reducer.option_catalog.complete
    assert reducer.catalog_options[name].instrument_name == name


def test_same_name_metadata_response_replaces_current_option_object(
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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    initial_payload = option_payload_factory(name=name, step=None)
    initial_payload.pop("min_trade_amount")
    reducer.reduce(
        response(
            catalog,
            [initial_payload],
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )
    assert reducer.options[name].amount is None

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
                seq=seq + 3,
            ),
            processed_monotonic_ms=1_003 + seq,
        ),
        RpcPurpose.OPTION_METADATA,
    )
    reducer.reduce(
        response(
            metadata,
            option_payload_factory(name=name, step=0.1),
            seq=seq + 4,
        ),
        processed_monotonic_ms=1_004 + seq,
    )

    assert reducer.options[name].amount is not None
    assert reducer.options[name] == reducer.catalog_options[name]


def test_valid_irrelevant_usdc_option_metadata_does_not_poison_btc_catalog(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)
    name = "ETH_USDC-TEST-3000-C"
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
                seq=seq,
            ),
            processed_monotonic_ms=1_000 + seq,
        ),
        RpcPurpose.OPTION_METADATA,
    )
    payload = option_payload_factory(name=name, strike=3_000)
    payload["base_currency"] = "ETH"
    payload["price_index"] = "eth_usdc"

    reducer.reduce(
        response(metadata, payload, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )

    assert name not in reducer.catalog_options
    assert reducer.option_catalog.complete


def test_temporary_option_lifecycle_state_retains_member_as_local_unknown(
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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        response(catalog, [option_payload_factory(name=name)], seq=seq + 2),
        processed_monotonic_ms=1_002 + seq,
    )

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": "halted"},
                },
            },
            seq=seq + 3,
        ),
        processed_monotonic_ms=1_003 + seq,
    )

    assert name in reducer.catalog_options
    assert name in reducer.options
    assert reducer.results[name].reason == "OPTION_LIFECYCLE_HALTED"
    assert reducer.option_catalog.complete


def test_unseen_temporary_lifecycle_state_stays_incomplete_until_identity_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)
    name = "BTC_USDC-UNKNOWN-HALTED"

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": "halted"},
                },
            },
            seq=seq,
        ),
        processed_monotonic_ms=1_000 + seq,
    )

    assert name not in reducer.catalog_options
    assert not reducer.option_catalog.complete
    assert reducer._next_option_catalog_recovery_ms is not None


@pytest.mark.parametrize(
    ("metadata_state", "is_active", "expected_reason"),
    [
        ("settlement", False, "OPTION_METADATA_SETTLEMENT"),
        ("locked", False, "OPTION_METADATA_LOCKED"),
        ("halted", False, "OPTION_METADATA_HALTED"),
        ("open", False, "OPTION_METADATA_OPEN_INACTIVE"),
    ],
)
def test_direct_option_metadata_cannot_recover_unavailable_contract_as_usable(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
    metadata_state: str,
    is_active: bool,
    expected_reason: str,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)
    name = "BTC_USDC-TEST-110000-C"
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
                seq=seq,
            ),
            processed_monotonic_ms=1_000 + seq,
        ),
        RpcPurpose.OPTION_METADATA,
    )
    payload = option_payload_factory(name=name)
    payload["state"] = metadata_state
    payload["is_active"] = is_active

    reducer.reduce(
        response(metadata, payload, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )

    assert reducer.option_catalog.complete
    assert name in reducer.catalog_options
    assert name in reducer.options
    assert reducer._option_lifecycle_unavailable[name] == expected_reason


@pytest.mark.parametrize(
    ("state", "expected_reason"),
    [
        ("settlement", "OPTION_SNAPSHOT_SETTLEMENT"),
        ("locked", "OPTION_SNAPSHOT_LOCKED"),
        ("halted", "OPTION_SNAPSHOT_HALTED"),
        ("open", "OPTION_SNAPSHOT_OPEN_INACTIVE"),
    ],
)
def test_bootstrap_unavailable_option_state_is_complete_local_unknown(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
    state: str,
    expected_reason: str,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    payload = option_payload_factory(name=name)
    payload["state"] = state
    payload["is_active"] = False

    reducer.reduce(
        response(catalog, [payload], seq=seq + 2),
        processed_monotonic_ms=1_002 + seq,
    )

    assert reducer.option_catalog.complete
    assert name in reducer.catalog_options
    assert name in reducer.options
    assert reducer._option_lifecycle_unavailable[name] == expected_reason


@pytest.mark.parametrize("state", ["inactive", "delivered", "archivized"])
def test_bootstrap_final_option_state_is_complete_and_out_of_scope(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
    state: str,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    payload = option_payload_factory(name=name)
    payload["state"] = state

    reducer.reduce(
        response(catalog, [payload], seq=seq + 2),
        processed_monotonic_ms=1_002 + seq,
    )

    assert reducer.option_catalog.complete
    assert name not in reducer.catalog_options
    assert name not in reducer.options
    assert name not in reducer._option_lifecycle_unavailable


def test_lifecycle_overflow_incompleteness_survives_snapshot_reconciliation(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    reducer.option_catalog.mark_incomplete()

    reducer.reduce(
        response(catalog, [], seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )

    assert not reducer.option_catalog.complete


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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"

    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": "inactive"},
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


def test_combo_refresh_repeats_until_one_generation_has_no_lifecycle_crossing(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    option_catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    first = only(commands, RpcPurpose.COMBO_CATALOG)
    reducer.reduce(
        response(option_catalog, [], seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    seq += 1

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
                            "state": "inactive",
                        },
                    },
                },
                seq=current_seq,
            ),
            processed_monotonic_ms=1_000 + current_seq,
        )
    third_commands = reducer.reduce(
        response(second, [], seq=seq + 10),
        processed_monotonic_ms=1_000 + seq + 10,
    )
    third = only(third_commands, RpcPurpose.COMBO_CATALOG)
    assert not reducer.combo_catalog.complete

    assert (
        reducer.reduce(
            response(third, [], seq=seq + 11),
            processed_monotonic_ms=1_000 + seq + 11,
        )
        == ()
    )
    assert reducer.combo_catalog.complete
    assert reducer.diagnostics.combo_authoritative_refresh_attempt_count == 3


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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    reducer.option_catalog.complete = True
    reducer.option_catalog.source_complete = True
    reducer.options = {
        "SHORT": _option_for_combo_test("SHORT", 100),
        "LONG": _option_for_combo_test("LONG", 110),
    }
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
                "is_active": True,
                "state": "open",
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


@pytest.mark.parametrize(
    ("metadata_state", "is_active"),
    [
        ("locked", True),
        ("halted", True),
        ("inactive", True),
        ("open", False),
    ],
)
def test_unavailable_combo_metadata_never_enters_atomic_catalog(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    metadata_state: str,
    is_active: bool,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    reducer.option_catalog.complete = True
    reducer.option_catalog.source_complete = True
    reducer.options = {
        "SHORT": _option_for_combo_test("SHORT", 100),
        "LONG": _option_for_combo_test("LONG", 110),
    }
    catalog = only(commands, RpcPurpose.COMBO_CATALOG)
    metadata = only(
        reducer.reduce(
            response(
                catalog,
                [
                    {
                        "id": "COMBO",
                        "state": "active",
                        "legs": [
                            {"instrument_name": "SHORT", "amount": -1},
                            {"instrument_name": "LONG", "amount": 1},
                        ],
                    }
                ],
                seq=seq + 1,
            ),
            processed_monotonic_ms=1_001 + seq,
        ),
        RpcPurpose.COMBO_METADATA,
    )

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
                "is_active": is_active,
                "state": metadata_state,
                "contract_size": 1,
                "min_trade_amount": 0.1,
                "qty_tick_size": 0.1,
            },
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )

    assert "COMBO" not in reducer.combos
    assert not reducer.combo_catalog.complete


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


def test_retired_epoch_is_not_established_or_platform_current(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer._bootstrap_queries_issued = True
    reducer.clock = TrustedClock.from_response(
        1_000_000,
        1_000,
        1_000,
        stale_deadline_ms=60_000,
    )
    reducer.option_catalog.complete = True
    reducer.platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    reducer.platform.apply_status({"locked": False})
    reducer.platform.apply_platform_notification({"maintenance": False})
    reducer.platform.apply_public_methods_notification(
        {"allow_unauthenticated_public_requests": True}
    )
    reducer.platform.note_post_status_probe()
    reducer.platform.note_fresh_index_coverage()
    assert reducer.session_established
    assert reducer.platform.usable

    reducer.prepare_reconnect("TEST_SESSION_GAP")

    assert not reducer.session_established
    assert not reducer.platform.usable


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


def test_source_shape_diagnostics_widen_mixed_json_numbers_once(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)

    reducer._note_source_shape(
        "public/get_instrument",
        {"min_trade_amount": 1},
        valid=True,
    )
    reducer._note_source_shape(
        "public/get_instrument",
        {"min_trade_amount": Decimal("0.1")},
        valid=True,
    )

    diagnostics = reducer._operational_diagnostics(1_000)
    rows = diagnostics["source_shapes"]
    assert isinstance(rows, list)
    row = next(item for item in rows if item["source"] == "public/get_instrument")
    assert row["consumed_fields"] == [{"key": "min_trade_amount", "type": "number"}]


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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
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
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
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
                    "data": {"instrument_name": name, "state": "inactive"},
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
