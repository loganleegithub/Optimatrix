from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import MethodType

import pytest
import radar_runtime.deribit_public as public_module
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
    CausalCause,
    CausalCommit,
    ChannelState,
    FactBoundary,
    FailureScope,
    PendingRpc,
    RadarReducer,
    RpcPurpose,
)
from short_vol_radar.detector import DetectorState, EpisodeTracker
from short_vol_radar.evidence import CoverageState, RadarEventSink
from short_vol_radar.policy import load_policy_bytes

_next_application_seq_by_epoch: dict[int, int] = {}


def next_application_seq(epoch: int) -> int:
    value = _next_application_seq_by_epoch.get(epoch, 1)
    _next_application_seq_by_epoch[epoch] = value + 1
    return value


def make_reducer(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> RadarReducer:
    _next_application_seq_by_epoch.clear()
    exact, digest = policy_factory()
    return RadarReducer(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        event_sink=RadarEventSink(
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
    application_seq: int | None = None,
) -> InboundEnvelope:
    return InboundEnvelope(
        {"jsonrpc": "2.0", **message},
        session_epoch=epoch,
        ingress_seq=(next_application_seq(epoch) if application_seq is None else application_seq),
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
    reducer: RadarReducer,
    command: PendingRpc,
    result: object,
    *,
    seq: int,
    received_ms: int | None = None,
) -> InboundEnvelope:
    reducer.reduce(
        send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=command.origin_boundary.received_monotonic_ms,
            ingress_seq=seq,
        ),
        processed_monotonic_ms=command.origin_boundary.received_monotonic_ms,
    )
    return envelope(
        {"id": command.request_id, "result": result},
        seq=seq,
        received_ms=received_ms,
        epoch=command.session_epoch,
    )


def send_control(
    command: PendingRpc,
    *,
    kind: str,
    boundary_ms: int,
    ingress_seq: int = 1,
    failure: str | None = None,
    application_seq: int | None = None,
) -> InboundEnvelope:
    del ingress_seq
    control_kind = public_module.SendControlKind(kind)
    failure_kind = None if failure is None else public_module.SendFailureKind(failure)
    return InboundEnvelope(
        {},
        session_epoch=command.session_epoch,
        ingress_seq=(
            next_application_seq(command.session_epoch)
            if application_seq is None
            else application_seq
        ),
        received_monotonic_ms=boundary_ms,
        control_event=public_module.SendControlEvent(
            kind=control_kind,
            request_id=command.request_id,
            boundary_monotonic_ms=boundary_ms,
            failure=failure_kind,
        ),
    )


def begin_through_bootstrap_subscribe(
    reducer: RadarReducer,
) -> tuple[PendingRpc, int]:
    heartbeat = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    commands = reducer.reduce(
        response(reducer, heartbeat, "ok", seq=1), processed_monotonic_ms=1_001
    )
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
            reducer,
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    option_catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    reducer.reduce(
        response(reducer, clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_000 + seq + 1,
    )
    reducer.reduce(
        response(reducer, option_catalog, [], seq=seq + 2),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    bootstrap = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    causal_before = reducer.causal_seq

    reducer.reduce(
        response(reducer, bootstrap, 1_000_000, seq=seq + 1),
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
        response(reducer, refresh, 1_000_001, seq=seq + 2),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=1, received_ms=1_001),
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
        response(reducer, refresh, 1_020_010, seq=2, received_ms=1_010),
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
                "data": {
                    "instrument_name": "BTC_USDC-08AUG26-100000-C",
                    "state": "closed",
                },
            },
        },
        seq=seq,
    )

    assert reducer.reduce(lifecycle, processed_monotonic_ms=1_002) == ()
    assert reducer.channel_state(channel) is ChannelState.SUBSCRIBE_PENDING
    assert reducer.option_catalog.buffered_events == []

    reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq + 1),
        processed_monotonic_ms=1_003,
    )

    assert reducer.channel_state(channel) is ChannelState.ACKNOWLEDGED
    assert reducer.option_catalog.buffered_events == [
        {
            "instrument_name": "BTC_USDC-08AUG26-100000-C",
            "state": "closed",
        }
    ]


def test_reordered_subscription_ack_commits_the_requested_batch(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    requested = exact_channels(subscribe)

    commands = reducer.reduce(
        response(reducer, subscribe, list(reversed(requested)), seq=seq),
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
            response(reducer, subscribe, requested[:-1], seq=seq + 1),
            processed_monotonic_ms=1_000 + seq + 1,
        )
    assert applied == []
    assert reducer._held_subscription_frame_count == 0


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
        response(reducer, subscribe, [first], seq=3),
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
        response(reducer, subscribe, [first], seq=1),
        processed_monotonic_ms=1_001,
    )

    assert reducer.channel_state(first) is ChannelState.ACKNOWLEDGED
    assert reducer.channel_state(second) is ChannelState.RETIRED
    assert reducer._channels[second].retry_after_ms is not None

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
        response(reducer, unsubscribe, [second], seq=2),
        processed_monotonic_ms=1_002,
    )

    assert reducer.channel_state(second) is ChannelState.RETIRED
    assert reducer.channel_state(first) is ChannelState.ACKNOWLEDGED
    assert reducer._channels[first].retry_after_ms is not None


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
        response(reducer, subscribe, [second, first], seq=1),
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
        response(reducer, subscribe, [channel], seq=2),
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
        send_control(
            unsubscribe,
            kind="SEND_COMPLETED",
            boundary_ms=unsubscribe.origin_boundary.received_monotonic_ms,
            ingress_seq=1,
        ),
        processed_monotonic_ms=unsubscribe.origin_boundary.received_monotonic_ms,
    )
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
        send_control(
            unsubscribe,
            kind="SEND_COMPLETED",
            boundary_ms=unsubscribe.origin_boundary.received_monotonic_ms,
            ingress_seq=1,
        ),
        processed_monotonic_ms=unsubscribe.origin_boundary.received_monotonic_ms,
    )
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
        response(reducer, request, ["alpha", "beta"], seq=seq + 2),
        processed_monotonic_ms=1_002 + seq,
    )

    assert applied == [3, 4]


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
        response(reducer, first, exact_channels(first), seq=3),
        processed_monotonic_ms=1_003,
    )
    assert applied == [2]

    reducer.reduce(
        response(reducer, second, exact_channels(second), seq=4),
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
        response(reducer, acknowledged, ["acknowledged"], seq=1),
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

    assert applied == [4]
    reducer.reduce(
        response(reducer, pending, ["pending"], seq=4),
        processed_monotonic_ms=1_004,
    )
    assert applied == [4, 3]


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
        commit = kwargs["commit"]
        assert isinstance(commit, CausalCommit)
        settled_causal.append(commit.boundary.causal_seq)
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
        response(reducer, subscribe, exact_channels(subscribe), seq=2, received_ms=1_002),
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
        send_control(
            first_clock,
            kind="SEND_COMPLETED",
            boundary_ms=first_clock.origin_boundary.received_monotonic_ms,
            ingress_seq=4,
        ),
        processed_monotonic_ms=first_clock.origin_boundary.received_monotonic_ms,
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
        response(reducer, recovered_clock, 660_000, seq=5, received_ms=1_005),
        processed_monotonic_ms=1_005,
    )

    assert len(applied) == 2
    assert [ingress_seq for ingress_seq, _causal_seq in applied] == [
        reducer._last_ingress_seq,
        reducer._last_ingress_seq,
    ]
    assert reducer._held_subscription_frame_count == 0
    assert reducer.index.has_accepted_tick
    assert reducer.index._last_source_timestamp_ms == 660_020
    assert reducer.index._working[660_000].price == Decimal(200)
    assert settled_causal == sorted(settled_causal)
    assert settled_causal[-1] > settled_causal[-2]


def test_queue_lag_edge_rebuilds_once_when_clock_releases_two_held_index_ticks(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    index_channel = "deribit_price_index.btc_usdc"
    reducer._plan_channel_change(
        (index_channel,),
        subscribe=True,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    subscribe = only(tuple(reducer.pending_rpcs.values()), RpcPurpose.SUBSCRIBE_CHANNELS)
    for seq, timestamp in ((1, 660_010), (3, 660_020)):
        reducer.reduce(
            envelope(
                {
                    "method": "subscription",
                    "params": {
                        "channel": index_channel,
                        "data": {
                            "timestamp": timestamp,
                            "price": 100,
                            "index_name": "btc_usdc",
                        },
                    },
                },
                seq=seq,
                received_ms=1_000 + seq,
            ),
            processed_monotonic_ms=1_000 + seq,
        )
        if seq == 1:
            reducer.reduce(
                response(
                    reducer,
                    subscribe,
                    exact_channels(subscribe),
                    seq=2,
                    received_ms=1_002,
                ),
                processed_monotonic_ms=1_002,
            )
    assert reducer._held_subscription_frame_count == 2

    clock = reducer._schedule(
        purpose=RpcPurpose.CLOCK_BOOTSTRAP,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=reducer._current_fact_boundary(),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    transactions: list[tuple[CausalCause, bool, bool]] = []
    settle_transaction = reducer._settle_fact_transaction

    def capture_transaction(**kwargs: object) -> None:
        commit = kwargs["commit"]
        force_full_currentness = kwargs["force_full_currentness"]
        countable = kwargs["countable"]
        assert isinstance(commit, CausalCommit)
        assert isinstance(force_full_currentness, bool)
        assert isinstance(countable, bool)
        transactions.append((commit.cause, force_full_currentness, countable))
        settle_transaction(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reducer, "_settle_fact_transaction", capture_transaction)
    delayed_clock = response(
        reducer,
        clock,
        660_000,
        seq=4,
        received_ms=1_004,
    )
    reducer.reduce(delayed_clock, processed_monotonic_ms=2_005)

    assert transactions == [
        (CausalCause.CLOCK_FACT, True, False),
        (CausalCause.INDEX_TICK, False, False),
        (CausalCause.INDEX_TICK, False, False),
    ]
    assert reducer._held_subscription_frame_count == 0


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
        response(reducer, subscribe, exact_channels(subscribe), seq=1, received_ms=1_050),
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
            reducer,
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
            reducer,
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
    assert reducer._last_wire_received_ms == 2_000


def test_retired_channel_generation_frame_has_zero_business_effect(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
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
        response(reducer, unsubscribe, exact_channels(unsubscribe), seq=seq + 1),
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


def test_every_frame_reduces_once_and_retired_epoch_has_zero_business_effect(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
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
    assert reducer.diagnostics.session_gap_count == 1

    current_heartbeat = next(iter(reducer.pending_rpcs.values()))
    reducer.reduce(
        response(reducer, current_heartbeat, "ok", seq=1, received_ms=2_001),
        processed_monotonic_ms=2_002,
    )
    duplicate_application_seq = reducer._last_ingress_seq
    with pytest.raises(PublicSessionError, match="sequence"):
        reducer.reduce(
            envelope(
                {"id": current_heartbeat.request_id, "result": "ok"},
                seq=1,
                epoch=2,
                received_ms=2_002,
                application_seq=duplicate_application_seq,
            ),
            processed_monotonic_ms=2_003,
        )


def test_retired_connection_error_drain_is_counted_with_bounded_attribution(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer._retire_current_epoch(
        CausalCause.RUNTIME_SESSION_FAILURE.value,
        monotonic_ms=1_050,
    )

    drained = InboundEnvelope(
        {
            "jsonrpc": "2.0",
            "method": "connection_error",
            "params": {
                "kind": "SESSION_FAILURE",
                "reason": "TRANSPORT_READ_FAILURE",
                "close_code": "NOT_AVAILABLE",
                "close_disposition": "ABNORMAL",
                "exception_class": "OSError",
            },
        },
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=1_100,
    )

    assert reducer.reduce(drained, processed_monotonic_ms=1_100) == ()


def test_session_epoch_cannot_be_reused_or_regressed(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=2, monotonic_ms=1_000)

    with pytest.raises(ValueError, match=r"increase|reused"):
        reducer.begin_session(session_epoch=2, monotonic_ms=2_000)
    with pytest.raises(ValueError, match=r"increase|reused"):
        reducer.begin_session(session_epoch=1, monotonic_ms=2_000)


def test_success_error_late_notification_and_heartbeat_response_reduce_once(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    combo = only(commands, RpcPurpose.COMBO_CATALOG)
    reducer.reduce(
        send_control(
            combo,
            kind="SEND_COMPLETED",
            boundary_ms=combo.origin_boundary.received_monotonic_ms,
            ingress_seq=seq + 1,
        ),
        processed_monotonic_ms=combo.origin_boundary.received_monotonic_ms,
    )
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
            reducer,
            heartbeat_command,
            {"version": "2.1.1"},
            seq=seq + 4,
        ),
        processed_monotonic_ms=1_004 + seq,
    )


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
def test_ordered_receive_lag_enters_currentness_without_retiring_session(
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
        delayed = response(reducer, heartbeat, "ok", seq=1, received_ms=1_001)
    else:
        subscribe, seq = begin_through_bootstrap_subscribe(reducer)
        reducer.reduce(
            response(reducer, subscribe, exact_channels(subscribe), seq=seq),
            processed_monotonic_ms=1_000 + seq,
        )
        delayed = envelope(
            {"method": "heartbeat", "params": {"type": "heartbeat"}},
            seq=seq + 1,
            received_ms=1_000 + seq + 1,
        )

    reducer.reduce(
        delayed,
        processed_monotonic_ms=delayed.received_monotonic_ms + 1_001,
    )

    assert reducer.diagnostics.session_gap_count == 0
    assert reducer._global_continuity_epoch == 1
    assert reducer._session_epoch not in reducer._retired_epochs
    assert reducer._queue_lag_currentness_active
    assert reducer._coverage._current_state is CoverageState.UNKNOWN
    assert reducer._coverage._current_blocking_reason == "QUEUE_LAG_CURRENTNESS"

    recovered = envelope(
        {"method": "heartbeat", "params": {"type": "heartbeat"}},
        seq=99,
        received_ms=delayed.received_monotonic_ms + 1_002,
    )
    reducer.reduce(
        recovered,
        processed_monotonic_ms=recovered.received_monotonic_ms,
    )

    assert not reducer._queue_lag_currentness_active
    assert reducer._coverage._current_blocking_reason != "QUEUE_LAG_CURRENTNESS"
    assert reducer.diagnostics.session_gap_count == 0


def test_queue_lag_is_not_a_reconnect_cause(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)

    with pytest.raises(ValueError, match="currentness"):
        reducer.prepare_reconnect("QUEUE_LAG_DEADLINE")

    assert reducer.diagnostics.session_gap_count == 0
    assert reducer._session_epoch not in reducer._retired_epochs


def test_negative_platform_guard_cannot_be_overwritten_in_same_epoch(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
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
            reducer,
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
        response(reducer, old_request, {"version": "1"}, seq=6),
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
        response(reducer, new_request, {"version": "1"}, seq=7),
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
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 1_000, 1),
            cause=CausalCause.PLATFORM_FACT,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    status = only(commands, RpcPurpose.PLATFORM_STATUS)

    with pytest.raises(PublicProtocolError, match="public/status"):
        reducer.reduce(
            response(reducer, status, {"locked": "unsupported"}, seq=seq + 1),
            processed_monotonic_ms=1_001 + seq,
        )


def test_post_status_schedules_the_official_btc_usdc_index_history_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, _seq = accept_platform_status(reducer, commands, seq=seq + 1)

    history = only(commands, RpcPurpose.INDEX_HISTORY)

    assert history.method == "public/get_index_chart_data"
    assert history.params == {"index_name": "btc_usdc", "range": "1d"}
    assert history.scope == "INDEX_HISTORY"
    assert history.failure_scope is FailureScope.CLOCK_INDEX
    assert RpcPurpose.INDEX_HISTORY not in runtime_module.POST_STATUS_BOOTSTRAP_PURPOSES


def test_invalid_index_history_shape_is_a_protocol_incompatibility(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    history = only(commands, RpcPurpose.INDEX_HISTORY)

    with pytest.raises(PublicProtocolError, match="get_index_chart_data"):
        reducer.reduce(
            response(reducer, history, {"unexpected": "shape"}, seq=seq + 1),
            processed_monotonic_ms=1_001 + seq,
        )


def test_index_history_rpc_failure_preserves_clock_and_last_valid_history(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.pending_rpcs.clear()
    clock = TrustedClock.from_response(
        600_000,
        1_000,
        1_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.clock = clock
    reducer.index_history.apply_chart_result([[0, 100], [300_000, 101]])
    history = reducer._schedule_index_history_refresh(reducer._current_fact_boundary())
    reducer.reduce(
        send_control(
            history,
            kind="SEND_COMPLETED",
            boundary_ms=history.origin_boundary.received_monotonic_ms,
        ),
        processed_monotonic_ms=history.origin_boundary.received_monotonic_ms,
    )

    reducer.reduce(
        envelope(
            {
                "id": history.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            seq=1,
            received_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    assert reducer.clock is clock
    assert [point.average_price for point in reducer.index_history.points] == [
        Decimal(100),
        Decimal(101),
    ]
    retry_commands = reducer.advance_time(1_001 + reducer.policy.runtime_limits.rpc_deadline_ms)
    retry = only(retry_commands, RpcPurpose.INDEX_HISTORY)
    assert retry.params == {"index_name": "btc_usdc", "range": "1d"}


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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    request = only(commands, RpcPurpose.PLATFORM_STATUS)

    with pytest.raises(PublicSessionError, match="RELEVANT_PLATFORM_LOCK"):
        reducer.reduce(
            response(reducer, request, status, seq=seq + 1),
            processed_monotonic_ms=1_001 + seq,
        )

    assert not reducer.platform.usable
    assert reducer.platform.reason == "RELEVANT_PLATFORM_LOCK"
    assert reducer.diagnostics.session_gap_count == 1
    assert reducer.pending_rpcs == {}


def test_blocked_send_keeps_scheduled_until_completed_receipt_starts_response_deadline(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    lifecycle = reducer._rpc_lifecycles[command.request_id]

    reducer.advance_time(30_000)

    assert lifecycle.state is runtime_module.RpcState.SCHEDULED
    assert lifecycle.sent_monotonic_ms is None
    assert lifecycle.response_deadline_monotonic_ms is None
    reducer.reduce(
        send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=30_000,
        ),
        processed_monotonic_ms=30_000,
    )
    lifecycle = reducer._rpc_lifecycles[command.request_id]
    assert lifecycle.state is runtime_module.RpcState.SENT
    assert lifecycle.sent_monotonic_ms == 30_000
    assert lifecycle.response_deadline_monotonic_ms == 60_000


@pytest.mark.parametrize("failure", ("CANCELLED", "ERROR"))
def test_send_cancel_and_failure_enter_reducer_as_terminal_control_events(
    failure: str,
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )

    with pytest.raises(PublicSessionError, match="SET_HEARTBEAT"):
        reducer.reduce(
            send_control(
                command,
                kind="SEND_FAILED",
                boundary_ms=1_200,
                failure=failure,
            ),
            processed_monotonic_ms=1_200,
        )

    lifecycle = reducer._rpc_lifecycles[command.request_id]
    assert lifecycle.state is runtime_module.RpcState.ERROR
    assert lifecycle.sent_monotonic_ms is None
    assert command.request_id not in reducer.pending_rpcs


def test_response_preceding_send_receipt_is_orphan_and_cannot_complete_request(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )

    assert (
        reducer.reduce(
            envelope(
                {"id": command.request_id, "result": "ok"},
                seq=1,
                received_ms=1_250,
            ),
            processed_monotonic_ms=1_250,
        )
        == ()
    )
    lifecycle = reducer._rpc_lifecycles[command.request_id]
    assert lifecycle.state is runtime_module.RpcState.SCHEDULED

    commands = reducer.reduce(
        send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=1_260,
            ingress_seq=2,
        ),
        processed_monotonic_ms=1_260,
    )

    lifecycle = reducer._rpc_lifecycles[command.request_id]
    assert lifecycle.state is runtime_module.RpcState.SENT
    assert commands == ()

    commands = reducer.reduce(
        envelope(
            {"id": command.request_id, "result": "ok"},
            seq=3,
            received_ms=1_270,
        ),
        processed_monotonic_ms=1_270,
    )

    lifecycle = reducer._rpc_lifecycles[command.request_id]
    assert lifecycle.state is runtime_module.RpcState.SUCCESS
    assert only(commands, RpcPurpose.SUBSCRIBE_CHANNELS)


def test_every_control_and_wire_event_advances_one_application_frontier(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )

    reducer.reduce(
        send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=1_100,
            ingress_seq=1,
        ),
        processed_monotonic_ms=1_100,
    )
    reducer.reduce(
        send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=1_101,
            ingress_seq=2,
        ),
        processed_monotonic_ms=1_101,
    )
    commands = reducer.reduce(
        envelope(
            {"id": command.request_id, "result": "ok"},
            seq=3,
            received_ms=1_102,
        ),
        processed_monotonic_ms=1_102,
    )

    assert reducer._last_ingress_seq == 3
    assert reducer._rpc_lifecycles[command.request_id].state is runtime_module.RpcState.SUCCESS
    assert only(commands, RpcPurpose.SUBSCRIBE_CHANNELS)


def test_duplicate_control_application_identity_fails_closed(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    control = send_control(
        command,
        kind="SEND_COMPLETED",
        boundary_ms=1_100,
        ingress_seq=1,
    )
    reducer.reduce(control, processed_monotonic_ms=1_100)

    with pytest.raises(PublicSessionError, match="sequence"):
        reducer.reduce(control, processed_monotonic_ms=1_101)


@pytest.mark.parametrize("event_kind", ("WIRE", "SEND_CONTROL", "CONNECTION_CONTROL"))
def test_application_sequence_gap_fails_closed_for_every_event_kind(
    event_kind: str,
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    if event_kind == "WIRE":
        event = envelope(
            {"method": "heartbeat", "params": {"type": "heartbeat"}},
            seq=2,
            received_ms=1_100,
            application_seq=2,
        )
    elif event_kind == "SEND_CONTROL":
        event = send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=1_100,
            application_seq=2,
        )
    else:
        event = InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "method": "connection_error",
                "params": {
                    "kind": "SESSION_FAILURE",
                    "reason": "TRANSPORT_READ_FAILURE",
                    "close_code": "NOT_AVAILABLE",
                    "close_disposition": "ABNORMAL",
                    "exception_class": "OSError",
                },
            },
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=1_100,
        )

    with pytest.raises(PublicSessionError, match="sequence"):
        reducer.reduce(event, processed_monotonic_ms=1_100)

    assert reducer._application_frontier_by_epoch[1] == 0


def test_local_send_control_does_not_refresh_wire_liveness(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.reduce(
        envelope(
            {
                "method": "heartbeat",
                "params": {"type": "heartbeat"},
            },
            seq=1,
            received_ms=1_002,
        ),
        processed_monotonic_ms=1_002,
    )
    reducer.reduce(
        InboundEnvelope(
            {},
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=61_000,
            control_event=public_module.SendControlEvent(
                kind=public_module.SendControlKind.SEND_COMPLETED,
                request_id=999_999,
                boundary_monotonic_ms=61_000,
            ),
        ),
        processed_monotonic_ms=61_000,
    )

    with pytest.raises(PublicSessionError, match="liveness"):
        reducer.advance_time(61_003)


def test_nonheartbeat_pre_sent_response_is_orphan_and_later_response_keeps_its_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    command = reducer._schedule(
        purpose=RpcPurpose.CLOCK_BOOTSTRAP,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=FactBoundary(1, 0, 1_000, 0),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    captured: list[CausalCommit] = []
    settle = reducer._settle_fact

    def capture_settlement(**kwargs: object) -> None:
        commit = kwargs["commit"]
        assert isinstance(commit, CausalCommit)
        captured.append(commit)
        settle(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reducer, "_settle_fact", capture_settlement)
    reducer.reduce(
        envelope(
            {"id": command.request_id, "result": 1_000_000},
            seq=1,
            received_ms=1_250,
        ),
        processed_monotonic_ms=1_250,
    )

    reducer.reduce(
        send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=1_260,
            ingress_seq=2,
        ),
        processed_monotonic_ms=1_260,
    )

    assert reducer.causal_seq == 0
    assert captured == []
    assert reducer._rpc_lifecycles[command.request_id].state is runtime_module.RpcState.SENT

    reducer.reduce(
        envelope(
            {"id": command.request_id, "result": 1_000_000},
            seq=3,
            received_ms=1_270,
        ),
        processed_monotonic_ms=1_270,
    )

    assert reducer.causal_seq == 1
    assert len(captured) == 1
    assert captured[0].boundary == FactBoundary(1, 3, 1_270, 1)


def test_send_cancellation_after_send_deadline_cannot_rewrite_terminal_state(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )

    with pytest.raises(PublicSessionError, match="SET_HEARTBEAT"):
        reducer.reduce(
            send_control(
                command,
                kind="SEND_FAILED",
                boundary_ms=31_002,
                failure="CANCELLED",
            ),
            processed_monotonic_ms=31_002,
        )

    lifecycle = reducer._rpc_lifecycles[command.request_id]
    assert lifecycle.state is runtime_module.RpcState.DEADLINE_LATE
    assert lifecycle.terminal_monotonic_ms == 31_002


def test_send_failure_cannot_rewrite_a_completed_send_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    command = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    reducer.reduce(
        send_control(
            command,
            kind="SEND_COMPLETED",
            boundary_ms=1_100,
            application_seq=1,
        ),
        processed_monotonic_ms=1_100,
    )

    with pytest.raises(PublicProtocolError, match=r"failure.*completed|completed.*failure"):
        reducer.reduce(
            send_control(
                command,
                kind="SEND_FAILED",
                boundary_ms=1_101,
                failure="ERROR",
                application_seq=2,
            ),
            processed_monotonic_ms=1_101,
        )

    lifecycle = reducer._rpc_lifecycles[command.request_id]
    assert lifecycle.state is runtime_module.RpcState.SENT
    assert lifecycle.terminal_monotonic_ms is None


def test_clean_stop_censors_scheduled_and_sent_without_collapsing_boundaries(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    scheduled = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    sent = reducer._schedule(
        purpose=RpcPurpose.CLOCK_BOOTSTRAP,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=FactBoundary(1, 0, 1_000, 0),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    reducer.reduce(
        send_control(
            sent,
            kind="SEND_COMPLETED",
            boundary_ms=1_100,
        ),
        processed_monotonic_ms=1_100,
    )

    reducer.clean_stop(1_200)

    scheduled_lifecycle = reducer._rpc_lifecycles[scheduled.request_id]
    sent_lifecycle = reducer._rpc_lifecycles[sent.request_id]
    assert scheduled_lifecycle.state is runtime_module.RpcState.CENSORED
    assert scheduled_lifecycle.sent_monotonic_ms is None
    assert sent_lifecycle.state is runtime_module.RpcState.CENSORED
    assert sent_lifecycle.sent_monotonic_ms == 1_100


def test_unsupported_target_option_lifecycle_enters_catalog_recovery_not_session_failure(
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
                    "data": {
                        "instrument_name": "BTC_USDC-08AUG26-100000-C",
                        "state": "future_protocol_state",
                    },
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
        response(reducer, metadata, option_payload_factory(name=name), seq=seq + 2),
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
        response(reducer, metadata, option_payload_factory(name=name), seq=seq + 1),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(reducer, clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    initial_payload = option_payload_factory(name=name, step=None)
    initial_payload.pop("min_trade_amount")
    reducer.reduce(
        response(
            reducer,
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
            reducer,
            metadata,
            option_payload_factory(name=name, step=0.1),
            seq=seq + 4,
        ),
        processed_monotonic_ms=1_004 + seq,
    )

    assert reducer.options[name].amount is not None
    assert reducer.options[name] == reducer.catalog_options[name]


@pytest.mark.parametrize(
    ("name", "state"),
    [
        ("ETH_USDC-08AUG26-3000-C", "open"),
        ("XRP_USDC-08AUG26-1-C", "future_protocol_state"),
    ],
)
def test_non_btc_usdc_lifecycle_is_shape_only_and_has_no_business_side_effect(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    name: str,
    state: str,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    seq = complete_empty_option_bootstrap(reducer)
    catalog_before = (
        dict(reducer.catalog_options),
        dict(reducer.options),
        reducer.option_catalog.complete,
        reducer.option_catalog.source_complete,
        dict(reducer._option_lifecycle_revision),
        dict(reducer._option_lifecycle_state),
        dict(reducer._option_metadata_pending),
        dict(reducer._option_lifecycle_unavailable),
    )
    coverage_before = (
        reducer._coverage._current_state,
        reducer._coverage._current_start_ms,
        reducer._coverage._current_trigger_cause,
        reducer._coverage._current_blocking_reason,
        tuple(reducer._coverage._segments),
    )
    pending_before = dict(reducer.pending_rpcs)

    commands = reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"instrument_name": name, "state": state},
                },
            },
            seq=seq,
        ),
        processed_monotonic_ms=1_000 + seq,
    )

    assert not any(command.purpose is RpcPurpose.OPTION_METADATA for command in commands)
    assert dict(reducer.pending_rpcs) == pending_before
    assert (
        dict(reducer.catalog_options),
        dict(reducer.options),
        reducer.option_catalog.complete,
        reducer.option_catalog.source_complete,
        dict(reducer._option_lifecycle_revision),
        dict(reducer._option_lifecycle_state),
        dict(reducer._option_metadata_pending),
        dict(reducer._option_lifecycle_unavailable),
    ) == catalog_before
    assert (
        reducer._coverage._current_state,
        reducer._coverage._current_start_ms,
        reducer._coverage._current_trigger_cause,
        reducer._coverage._current_blocking_reason,
        tuple(reducer._coverage._segments),
    ) == coverage_before


def test_temporary_option_lifecycle_state_retains_member_as_local_unknown(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(reducer, clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        response(reducer, catalog, [option_payload_factory(name=name)], seq=seq + 2),
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
        response(reducer, metadata, payload, seq=seq + 1),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(reducer, clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    payload = option_payload_factory(name=name)
    payload["state"] = state
    payload["is_active"] = False

    reducer.reduce(
        response(reducer, catalog, [payload], seq=seq + 2),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(reducer, clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    payload = option_payload_factory(name=name)
    payload["state"] = state

    reducer.reduce(
        response(reducer, catalog, [payload], seq=seq + 2),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    reducer.option_catalog.mark_incomplete()

    reducer.reduce(
        response(reducer, catalog, [], seq=seq + 1),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    existing = "BTC_USDC-TEST-100010-C"
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(reducer, clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    dynamic = reducer.reduce(
        response(
            reducer,
            catalog,
            [option_payload_factory(name=existing, strike=100_010)],
            seq=seq + 2,
        ),
        processed_monotonic_ms=1_002 + seq,
    )
    next_seq = seq + 3
    for command in tuple(item for item in dynamic if item.purpose is RpcPurpose.SUBSCRIBE_CHANNELS):
        reducer.reduce(
            response(reducer, command, exact_channels(command), seq=next_seq),
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
        response(reducer, metadata, option_payload_factory(name=name), seq=next_seq),
        processed_monotonic_ms=1_000 + next_seq,
    )

    assert name in reducer.catalog_options


def test_close_while_option_snapshot_is_pending_wins_over_old_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
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
            reducer,
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    option_catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    first = only(commands, RpcPurpose.COMBO_CATALOG)
    reducer.reduce(
        response(reducer, option_catalog, [], seq=seq + 1),
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
        response(reducer, first, [], seq=seq + 6),
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
        response(reducer, second, [], seq=seq + 10),
        processed_monotonic_ms=1_000 + seq + 10,
    )
    third = only(third_commands, RpcPurpose.COMBO_CATALOG)
    assert not reducer.combo_catalog.complete

    assert (
        reducer.reduce(
            response(reducer, third, [], seq=seq + 11),
            processed_monotonic_ms=1_000 + seq + 11,
        )
        == ()
    )
    assert reducer.combo_catalog.complete


def test_nonempty_combo_catalog_fetches_metadata_once_and_reuses_unchanged(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
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
        response(reducer, catalog, [summary], seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    metadata = only(metadata_commands, RpcPurpose.COMBO_METADATA)
    reducer.reduce(
        response(
            reducer,
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

    refresh = reducer._schedule_combo_refresh(reducer._current_fact_boundary())
    assert (
        reducer.reduce(
            response(reducer, refresh, [summary], seq=seq + 3),
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
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
                reducer,
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
            reducer,
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
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )

    reducer.prepare_reconnect("TEST_SESSION_GAP")
    reducer.prepare_reconnect("DUPLICATE_NOTICE")
    reducer.begin_session(session_epoch=2, monotonic_ms=2_000)

    assert reducer.diagnostics.session_gap_count == 1
    assert reducer.diagnostics.reconnect_count == 1


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


def test_incomplete_option_snapshot_cannot_create_membership_loss(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: OptionPayloadFactory,
) -> None:
    reducer = make_reducer(tmp_path, policy_factory)
    subscribe, seq = begin_through_bootstrap_subscribe(reducer)
    commands = reducer.reduce(
        response(reducer, subscribe, exact_channels(subscribe), seq=seq),
        processed_monotonic_ms=1_000 + seq,
    )
    commands, seq = accept_platform_status(reducer, commands, seq=seq + 1)
    clock = only(commands, RpcPurpose.CLOCK_BOOTSTRAP)
    catalog = only(commands, RpcPurpose.OPTION_CATALOG)
    name = "BTC_USDC-TEST-110000-C"
    reducer.reduce(
        response(reducer, clock, 1_000_000, seq=seq + 1),
        processed_monotonic_ms=1_001 + seq,
    )
    reducer.reduce(
        response(
            reducer,
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
            reducer,
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
            reducer,
            recovery,
            [option_payload_factory(name=name)],
            seq=seq + 1,
            received_ms=2_002,
        ),
        processed_monotonic_ms=2_002,
    )

    assert name not in reducer.catalog_options
    assert reducer.option_catalog.complete
