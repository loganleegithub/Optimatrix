from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import radar_runtime.runtime as runtime_module
from conftest import PolicyFactory, encode_policy, policy_document
from market_monitor import (
    ContinuousOrderBook,
    IndexTail,
    IndexTailStatus,
    TimeInterval,
    TrustedClock,
)
from market_monitor.deribit import INDEX_CHANNEL, PLATFORM_CHANNELS, book_channel, ticker_channel
from options_domain import (
    AmountMetadata,
    ComboInstrument,
    ComboLeg,
    OptionInstrument,
    OptionType,
)
from radar_runtime.deribit_public import InboundEnvelope, PublicSessionError
from radar_runtime.runtime import (
    ChannelState,
    FactBoundary,
    FailureScope,
    RadarReducer,
    RpcPurpose,
)
from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.black import DecimalInterval
from short_vol_radar.detector import (
    DetectorObservation,
    DetectorState,
    EpisodeEndReason,
    EpisodeTracker,
)
from short_vol_radar.evidence import CoverageState, EvidenceWriter
from short_vol_radar.policy import RadarPolicy, load_policy_bytes
from short_vol_radar.radar import TickerState


def make_reducer(tmp_path: Path, policy: RadarPolicy) -> RadarReducer:
    reducer = RadarReducer(
        policy=policy,
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=policy.identity,
        ),
        runtime_identity="runtime",
    )
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.clock = TrustedClock.from_response(
        1_000_000,
        1_000,
        1_000,
        stale_deadline_ms=policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.platform.acknowledge(PLATFORM_CHANNELS)
    reducer.platform.apply_status({"locked": False})
    reducer.platform.apply_platform_notification({"maintenance": False})
    reducer.platform.apply_public_methods_notification(
        {"allow_unauthenticated_public_requests": True}
    )
    reducer.platform.note_post_status_probe()
    reducer.platform.note_fresh_index_coverage()
    assert reducer.platform.usable
    reducer.option_catalog.complete = True
    reducer.option_catalog.source_complete = True
    return reducer


def make_option(name: str, expiry_ms: int, *, amount_known: bool = True) -> OptionInstrument:
    return OptionInstrument(
        name,
        expiry_ms,
        Decimal("100.01"),
        OptionType.CALL,
        (AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")) if amount_known else None),
    )


def make_book(name: str, price: str | None) -> ContinuousOrderBook:
    book = ContinuousOrderBook(name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": name,
            "change_id": 1,
            "bids": [] if price is None else [["new", price, "0.1"]],
            "asks": [],
        },
        1_000,
    )
    return book


def acknowledge_channel(
    reducer: RadarReducer,
    channel: str,
    *,
    generation: int = 1,
) -> None:
    reducer._channels[channel] = runtime_module._ChannelSlot(
        state=ChannelState.ACKNOWLEDGED,
        generation=generation,
        desired_subscribed=True,
    )
    reducer._next_channel_generation = max(
        reducer._next_channel_generation,
        generation + 1,
    )


def subscription_frame(
    channel: str,
    data: object,
    *,
    ingress_seq: int,
    received_monotonic_ms: int,
) -> InboundEnvelope:
    return InboundEnvelope(
        {
            "jsonrpc": "2.0",
            "method": "subscription",
            "params": {"channel": channel, "data": data},
        },
        session_epoch=1,
        ingress_seq=ingress_seq,
        received_monotonic_ms=received_monotonic_ms,
    )


def seed_available_index(reducer: RadarReducer) -> None:
    reducer.index.start_continuous_coverage(600_000)
    for causal_seq, timestamp in enumerate(
        (600_001, 660_000, 720_000, 780_000, 840_000, 900_000, 960_000),
        start=1,
    ):
        reducer.index.accept_tick(
            source_timestamp_ms=timestamp,
            price=100 + causal_seq,
            causal_seq=causal_seq,
        )
        reducer.index.seal_ready(timestamp)


def seed_flat_available_index(reducer: RadarReducer) -> None:
    reducer.index.start_continuous_coverage(600_000)
    for causal_seq, timestamp in enumerate(
        (600_001, 660_000, 720_000, 780_000, 840_000, 900_000, 960_000),
        start=1,
    ):
        reducer.index.accept_tick(
            source_timestamp_ms=timestamp,
            price=100,
            causal_seq=causal_seq,
        )
        reducer.index.seal_ready(timestamp)


def activate_directly(
    reducer: RadarReducer,
    instrument: OptionInstrument,
    *,
    band_index: int = 0,
) -> str:
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=instrument.instrument_name,
    )
    rule = reducer.policy.tte_bands[band_index].option_rules[OptionType.CALL]
    transition = tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(1_000_000, 1_000_000),
            band_id=reducer.policy.tte_bands[band_index].band_id,
            richness=DecimalInterval(Decimal(2), Decimal(2)),
        ),
        rule,
    )
    assert transition.activated_episode_id is not None
    reducer.trackers[instrument.instrument_name] = tracker
    return transition.activated_episode_id


def test_one_global_index_gap_makes_every_instrument_unknown_in_same_fact_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("BTC_USDC-27SEP24-100010-C", expiry)
    second = make_option("BTC_USDC-27SEP24-100020-C", expiry)
    reducer.options = {first.instrument_name: first, second.instrument_name: second}
    reducer.catalog_options = dict(reducer.options)
    activate_directly(reducer, first)
    activate_directly(reducer, second)
    reducer.option_books = {
        first.instrument_name: make_book(first.instrument_name, "1"),
        second.instrument_name: make_book(second.instrument_name, "1"),
    }
    reducer.tickers = {
        first.instrument_name: TickerState(Decimal(100), "index_price", 1),
        second.instrument_name: TickerState(Decimal(100), "index_price", 1),
    }
    reducer.index.gap()

    reducer.settle_fact(
        boundary=FactBoundary(1, 1, 1_001, 2),
        affected_instruments=(first.instrument_name,),
        countable=False,
        observation_reason="INDEX_FACT",
    )

    assert reducer.trackers[first.instrument_name].detector_state is DetectorState.UNKNOWN
    assert reducer.trackers[second.instrument_name].detector_state is DetectorState.UNKNOWN
    assert reducer.results[first.instrument_name].reason == "INDEX_CONTINUITY_GAP"
    assert reducer.results[second.instrument_name].reason == "INDEX_CONTINUITY_GAP"


def test_index_regression_commits_platform_detector_aggregate_and_coverage_atomically(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[instrument.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=instrument.instrument_name,
    )
    reducer.option_books[instrument.instrument_name] = make_book(
        instrument.instrument_name,
        None,
    )
    reducer.settle_fact(
        boundary=FactBoundary(1, 1, 1_001, 1),
        affected_instruments=(instrument.instrument_name,),
        countable=True,
    )
    assert reducer.results[instrument.instrument_name].known_evaluation
    assert reducer._coverage._current_state.value == CoverageState.KNOWN_COMPLETE.value

    assert not reducer._apply_index(
        {
            "timestamp": 900_000,
            "price": 100,
            "index_name": "btc_usdc",
        },
        FactBoundary(1, 2, 1_002, 2),
    )

    assert not reducer.platform.usable
    assert reducer.platform.reason == "INDEX_CONTINUITY_GAP"
    assert reducer.results[instrument.instrument_name].reason == "INDEX_CONTINUITY_GAP"
    assert reducer.trackers[instrument.instrument_name].detector_state is DetectorState.UNKNOWN
    assert all(
        aggregate.state is DetectorState.UNKNOWN for aggregate in reducer.aggregate_results.values()
    )
    assert reducer._coverage._current_state.value == CoverageState.UNKNOWN.value
    assert reducer.atomic_states == {}


def test_clock_refresh_failure_keeps_fresh_clock_until_real_stale_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    reducer.pending_rpcs.clear()
    seed_available_index(reducer)
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    episode_id = activate_directly(reducer, instrument)
    sealed_before_failure = reducer.index.sealed
    request = reducer._schedule(
        purpose=RpcPurpose.CLOCK_REFRESH,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=FactBoundary(1, 0, 1_000, 1),
        failure_scope=FailureScope.CLOCK_INDEX,
    )

    commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": request.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    assert commands == ()
    assert reducer.clock is not None
    assert reducer.index.sealed == sealed_before_failure
    assert reducer.trackers[instrument.instrument_name].episode_id == episode_id

    stale_commands = reducer.advance_time(61_000)

    assert reducer.clock is None
    assert reducer.index.sealed == ()
    assert reducer.trackers[instrument.instrument_name].episode_id is None
    assert any(command.purpose is RpcPurpose.CLOCK_BOOTSTRAP for command in stale_commands)


def test_clock_refresh_response_settles_final_window_in_same_fact_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 30 * 60_000 + 50
    instrument = make_option("BTC_USDC-27SEP24-100010-C", expiry)
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    activate_directly(reducer, instrument)

    refresh = reducer._schedule(
        purpose=RpcPurpose.CLOCK_REFRESH,
        method="public/get_time",
        params={},
        scope="CLOCK_INDEX",
        generation=None,
        origin_boundary=FactBoundary(1, 0, 1_000, 1),
        failure_scope=FailureScope.CLOCK_INDEX,
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": refresh.request_id,
                "result": 1_000_100,
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_100,
        ),
        processed_monotonic_ms=1_100,
    )

    assert reducer.trackers[instrument.instrument_name].episode_id is None
    assert reducer._episode_end_counts[EpisodeEndReason.OUT_OF_BASELINE_SCOPE.value] == 1


def test_negative_platform_guard_ends_episode_once_as_session_gap(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    activate_directly(reducer, instrument)

    with pytest.raises(PublicSessionError, match="PLATFORM_MAINTENANCE"):
        reducer._apply_acknowledged_subscription(
            InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "subscription",
                    "params": {
                        "channel": "platform_state",
                        "data": {"maintenance": True},
                    },
                },
                session_epoch=1,
                ingress_seq=1,
                received_monotonic_ms=1_001,
            )
        )

    assert reducer.platform.reason == "PLATFORM_MAINTENANCE"
    assert reducer.results[instrument.instrument_name].reason == "SESSION_GAP"
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 1
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 0


def test_final_window_time_poll_ends_whole_scope_without_market_update(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 30 * 60_000 + 500
    first = make_option("BTC_USDC-27SEP24-100010-C", expiry)
    second = make_option("BTC_USDC-27SEP24-100020-C", expiry)
    reducer.options = {first.instrument_name: first, second.instrument_name: second}
    reducer.catalog_options = dict(reducer.options)
    first_episode = activate_directly(reducer, first)
    second_episode = activate_directly(reducer, second)

    reducer.advance_time(1_600)

    assert reducer.trackers[first.instrument_name].episode_id is None
    assert reducer.trackers[second.instrument_name].episode_id is None
    assert reducer._episode_end_counts[EpisodeEndReason.OUT_OF_BASELINE_SCOPE.value] == 2
    assert first_episode != second_episode


def test_policy_gap_time_poll_ends_whole_scope_without_market_update(
    tmp_path: Path,
) -> None:
    document = policy_document(activation_count=1)
    bands = document["tte_bands"]
    assert isinstance(bands, list)
    bands[0]["upper_bound_minutes"] = 300
    bands[1]["lower_bound_minutes"] = 420
    exact, digest = encode_policy(document)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 420 * 60_000 + 500
    first = make_option("BTC_USDC-27SEP24-100010-C", expiry)
    second = make_option("BTC_USDC-27SEP24-100020-C", expiry)
    reducer.options = {first.instrument_name: first, second.instrument_name: second}
    reducer.catalog_options = dict(reducer.options)
    activate_directly(reducer, first, band_index=1)
    activate_directly(reducer, second, band_index=1)

    reducer.advance_time(1_600)

    assert reducer.trackers[first.instrument_name].episode_id is None
    assert reducer.trackers[second.instrument_name].episode_id is None
    assert reducer._episode_end_counts[EpisodeEndReason.OUT_OF_BASELINE_SCOPE.value] == 2


def test_amount_unknown_to_valid_establishes_known_current_without_activation_count(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    unknown = make_option("BTC_USDC-27SEP24-100010-C", expiry, amount_known=False)
    reducer.options = {unknown.instrument_name: unknown}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[unknown.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=unknown.instrument_name,
    )
    reducer.option_books[unknown.instrument_name] = make_book(unknown.instrument_name, "1")
    reducer.tickers[unknown.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_001,
    )

    reducer.settle_fact(
        boundary=FactBoundary(1, 1, 1_001, 1),
        affected_instruments=(unknown.instrument_name,),
        countable=True,
    )
    assert reducer.trackers[unknown.instrument_name].detector_state is DetectorState.UNKNOWN

    valid = make_option(unknown.instrument_name, expiry, amount_known=True)
    reducer.options[valid.instrument_name] = valid
    reducer.catalog_options[valid.instrument_name] = valid
    reducer.settle_fact(
        boundary=FactBoundary(1, 2, 1_002, 2),
        affected_instruments=(valid.instrument_name,),
        countable=False,
        observation_reason="OPTION_METADATA",
    )

    result = reducer.results[valid.instrument_name]
    assert result.known_evaluation
    assert not result.observation_eligible
    assert reducer.trackers[valid.instrument_name].detector_state is DetectorState.NO_ANOMALY
    assert reducer.trackers[valid.instrument_name].episode_id is None


def test_active_amount_loss_ends_episode_and_layer_two_in_same_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    valid = make_option("BTC_USDC-27SEP24-100010-C", expiry)
    reducer.options = {valid.instrument_name: valid}
    reducer.catalog_options = dict(reducer.options)
    episode_id = activate_directly(reducer, valid)
    reducer.atomic_states[episode_id] = PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE
    reducer.option_books[valid.instrument_name] = make_book(valid.instrument_name, "1")
    reducer.tickers[valid.instrument_name] = TickerState(Decimal(100), "index_price", 1)

    missing = make_option(valid.instrument_name, expiry, amount_known=False)
    reducer.options[missing.instrument_name] = missing
    reducer.catalog_options[missing.instrument_name] = missing
    reducer.settle_fact(
        boundary=FactBoundary(1, 1, 1_001, 1),
        affected_instruments=(missing.instrument_name,),
        countable=False,
        observation_reason="OPTION_METADATA",
    )

    assert reducer.trackers[missing.instrument_name].episode_id is None
    assert episode_id not in reducer.atomic_states
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1


def test_ticker_regression_preserves_gap_reason_and_ends_episode_at_gap(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books[instrument.instrument_name] = make_book(
        instrument.instrument_name,
        "1",
    )
    reducer.tickers[instrument.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        2,
    )
    activate_directly(reducer, instrument)

    assert not reducer._apply_ticker(
        instrument.instrument_name,
        {
            "instrument_name": instrument.instrument_name,
            "timestamp": 1,
            "underlying_price": 100,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 1, 1_001, 2),
    )

    assert reducer.results[instrument.instrument_name].reason == "TICKER_CONTINUITY_GAP"
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 1


def test_ticker_gap_quarantines_old_generation_until_resubscribe_ack(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    name = "BTC_USDC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    reducer.options = {name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books[name] = make_book(name, "1")
    reducer.tickers[name] = TickerState(Decimal(100), "index_price", 2)
    activate_directly(reducer, instrument)
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel)

    assert not reducer._apply_ticker(
        name,
        {
            "instrument_name": name,
            "timestamp": 1,
            "underlying_price": 100,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 1, 1_001, 2),
    )
    assert reducer.results[name].reason == "TICKER_CONTINUITY_GAP"
    assert reducer._channels[channel].resync_requested

    reducer._accept_subscription_frame(
        subscription_frame(
            channel,
            {
                "instrument_name": name,
                "timestamp": 3,
                "underlying_price": 100,
                "underlying_index": "index_price",
            },
            ingress_seq=2,
            received_monotonic_ms=1_002,
        )
    )

    assert name not in reducer.tickers
    assert reducer.results[name].reason == "TICKER_CONTINUITY_GAP"
    assert reducer.trackers[name].episode_id is None
    assert not tuple(tmp_path.glob("short-vol-anomaly-*.json"))


def test_ticker_staleness_is_fail_closed_latched_and_same_forward_recovery_is_not_countable(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=1_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    name = "BTC_USDC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    reducer.options = {name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=name,
    )
    reducer.option_books[name] = make_book(name, "1")
    reducer.tickers[name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_001,
    )
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel)
    acknowledge_channel(reducer, book_channel(name))
    acknowledge_channel(reducer, INDEX_CHANNEL)
    reducer._causal_seq = 1
    reducer.settle_fact(
        boundary=FactBoundary(1, 0, 1_000, 1),
        affected_instruments=(name,),
        countable=True,
    )
    episode_id = reducer.trackers[name].episode_id
    assert episode_id is not None
    reducer.atomic_states[episode_id] = PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE

    assert reducer.advance_time(1_999) == ()
    assert reducer.trackers[name].episode_id == episode_id
    commands = reducer.advance_time(2_000)

    assert reducer.results[name].reason == "TICKER_SOURCE_STALE"
    assert reducer.trackers[name].episode_id is None
    assert reducer.trackers[name].detector_state is DetectorState.UNKNOWN
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 1
    assert episode_id not in reducer.atomic_states
    assert reducer._atomic_transition_counts[PublicAtomicQuoteState.NOT_EVALUATED.value] == 1
    assert reducer.tickers[name].source_timestamp_ms == 1_000_001
    assert reducer.channel_state(channel) is ChannelState.UNSUBSCRIBE_PENDING
    unsubscribe = next(
        command for command in commands if command.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )

    reducer.clock = TrustedClock(
        base=TimeInterval(1_000_999, 1_001_000),
        base_monotonic_ms=2_000,
        last_refresh_monotonic_ms=2_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.settle_fact(
        boundary=FactBoundary(1, 0, 2_000, reducer.causal_seq),
        affected_instruments=(name,),
        countable=False,
        observation_reason="CLOCK_REFRESH",
    )
    assert reducer.results[name].reason == "TICKER_SOURCE_STALE"
    assert not tuple(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
        and request.request_id != unsubscribe.request_id
    )

    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": unsubscribe.request_id,
                "result": unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )
    subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "result": subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=2_002,
        ),
        processed_monotonic_ms=2_002,
    )
    recovered_timestamp = reducer.clock.interval_at(2_003).upper_ms
    reducer.reduce(
        subscription_frame(
            channel,
            {
                "instrument_name": name,
                "timestamp": recovered_timestamp,
                "underlying_price": 100,
                "underlying_index": "index_price",
            },
            ingress_seq=3,
            received_monotonic_ms=2_003,
        ),
        processed_monotonic_ms=2_003,
    )

    assert reducer.results[name].known_evaluation
    assert reducer.results[name].reason is None
    assert not reducer.results[name].observation_eligible
    assert reducer.trackers[name].state.name == "ARMED"
    assert reducer.trackers[name].episode_id is None
    assert len(tuple(tmp_path.glob("short-vol-anomaly-*.json"))) == 1


def test_same_forward_ticker_recovery_cannot_count_book_change_during_staleness(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=1_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    name = "BTC_USDC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    reducer.options = {name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=name,
    )
    reducer.option_books[name] = make_book(name, "1")
    reducer.tickers[name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_001,
    )
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel)
    acknowledge_channel(reducer, book_channel(name))
    acknowledge_channel(reducer, INDEX_CHANNEL)
    reducer._causal_seq = 1
    reducer.settle_fact(
        boundary=FactBoundary(1, 0, 1_000, 1),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.trackers[name].episode_id is not None
    assert len(tuple(tmp_path.glob("short-vol-anomaly-*.json"))) == 1

    commands = reducer.advance_time(2_000)
    unsubscribe = next(
        command for command in commands if command.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        subscription_frame(
            book_channel(name),
            {
                "type": "change",
                "timestamp": 2,
                "instrument_name": name,
                "change_id": 2,
                "prev_change_id": 1,
                "bids": [["delete", "1", "0"], ["new", "2", "0.1"]],
                "asks": [],
            },
            ingress_seq=1,
            received_monotonic_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )
    assert reducer.results[name].reason == "TICKER_SOURCE_STALE"

    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": unsubscribe.request_id,
                "result": unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=2_002,
        ),
        processed_monotonic_ms=2_002,
    )
    subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "result": subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=3,
            received_monotonic_ms=2_003,
        ),
        processed_monotonic_ms=2_003,
    )
    assert reducer.clock is not None
    recovered_timestamp = reducer.clock.interval_at(2_004).upper_ms
    reducer.reduce(
        subscription_frame(
            channel,
            {
                "instrument_name": name,
                "timestamp": recovered_timestamp,
                "underlying_price": 100,
                "underlying_index": "index_price",
            },
            ingress_seq=4,
            received_monotonic_ms=2_004,
        ),
        processed_monotonic_ms=2_004,
    )

    assert reducer.results[name].known_evaluation
    assert reducer.results[name].reason is None
    assert not reducer.results[name].observation_eligible
    assert reducer.trackers[name].state.name == "ARMED"
    assert reducer.trackers[name].episode_id is None
    assert len(tuple(tmp_path.glob("short-vol-anomaly-*.json"))) == 1


def test_ticker_resubscribe_error_preserves_book_raw_fact_and_noncountable_recovery(
    tmp_path: Path,
) -> None:
    document = policy_document(
        activation_count=1,
        ticker_source_stale_deadline_ms=1_000,
    )
    runtime_limits = document["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    runtime_limits["rpc_deadline_ms"] = 1_000
    exact, digest = encode_policy(document)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    reducer.pending_rpcs.clear()
    seed_flat_available_index(reducer)
    name = "BTC_USDC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    reducer.options = {name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=name,
    )
    book = make_book(name, "1")
    reducer.option_books[name] = book
    reducer.tickers[name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_001,
    )
    ticker_subscription = ticker_channel(name)
    acknowledge_channel(reducer, ticker_subscription)
    acknowledge_channel(reducer, book_channel(name))
    acknowledge_channel(reducer, INDEX_CHANNEL)
    reducer._causal_seq = 1
    reducer.settle_fact(
        boundary=FactBoundary(1, 0, 1_000, 1),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.trackers[name].episode_id is not None

    commands = reducer.advance_time(2_000)
    first_unsubscribe = next(
        command for command in commands if command.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": first_unsubscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )

    assert reducer.option_books[name] is book
    assert book.state.name == "USABLE"
    assert reducer.tickers[name].source_timestamp_ms == 1_000_001
    assert name in reducer._ticker_currentness_latches
    assert reducer._next_option_catalog_recovery_ms is None

    retry_commands = reducer.advance_time(3_001)
    assert not any(command.purpose is RpcPurpose.OPTION_CATALOG for command in retry_commands)
    retry_unsubscribe = next(
        command for command in retry_commands if command.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": retry_unsubscribe.request_id,
                "result": retry_unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=3_002,
        ),
        processed_monotonic_ms=3_002,
    )
    subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "result": subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=3,
            received_monotonic_ms=3_003,
        ),
        processed_monotonic_ms=3_003,
    )
    assert reducer.clock is not None
    recovered_timestamp = reducer.clock.interval_at(3_004).upper_ms
    reducer.reduce(
        subscription_frame(
            ticker_subscription,
            {
                "instrument_name": name,
                "timestamp": recovered_timestamp,
                "underlying_price": 100,
                "underlying_index": "index_price",
            },
            ingress_seq=4,
            received_monotonic_ms=3_004,
        ),
        processed_monotonic_ms=3_004,
    )

    assert reducer.option_books[name] is book
    assert book.state.name == "USABLE"
    assert reducer.results[name].known_evaluation
    assert reducer.results[name].reason is None
    assert not reducer.results[name].observation_eligible
    assert reducer.trackers[name].state.name == "ARMED"
    assert reducer.trackers[name].episode_id is None
    assert name not in reducer._ticker_currentness_latches
    assert reducer._next_option_catalog_recovery_ms is None


def test_ticker_channel_rpc_failure_preserves_known_insufficient_book_depth(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    reducer.pending_rpcs.clear()
    seed_flat_available_index(reducer)
    name = "BTC_USDC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    reducer.options = {name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=name,
    )
    reducer.option_books[name] = make_book(name, None)
    reducer.tickers[name] = TickerState(Decimal(100), "index_price", 1_000_001)
    reducer.settle_fact(
        boundary=FactBoundary(1, 0, 1_000, 1),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.results[name].known_evaluation
    assert reducer.results[name].reason == "INSUFFICIENT_TARGET_BID_DEPTH"
    reducer._plan_channel_change(
        (ticker_channel(name),),
        subscribe=True,
        origin_boundary=FactBoundary(1, 0, 1_000, 1),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )

    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    result = reducer.results[name]
    assert result.known_evaluation
    assert result.reason == "INSUFFICIENT_TARGET_BID_DEPTH"
    assert result.current_evaluation is not None
    assert not result.current_evaluation.continuity_gap


@pytest.mark.parametrize(
    ("failed_channel_kinds", "expected_book_state", "expected_ticker_gap"),
    (
        (("ticker",), "USABLE", True),
        (("book",), "UNKNOWN", False),
        (("ticker", "book"), "UNKNOWN", True),
    ),
)
def test_option_channel_rpc_failure_is_scoped_to_exact_failed_channels(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    failed_channel_kinds: tuple[str, ...],
    expected_book_state: str,
    expected_ticker_gap: bool,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    reducer.pending_rpcs.clear()
    seed_flat_available_index(reducer)
    name = "BTC_USDC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    reducer.options = {name: instrument}
    reducer.catalog_options = dict(reducer.options)
    activate_directly(reducer, instrument)
    book = make_book(name, "1")
    ticker = TickerState(Decimal(100), "index_price", 1_000_001)
    reducer.option_books[name] = book
    reducer.tickers[name] = ticker
    channels_by_kind = {
        "ticker": ticker_channel(name),
        "book": book_channel(name),
    }
    failed_channels = tuple(channels_by_kind[kind] for kind in failed_channel_kinds)
    reducer._plan_channel_change(
        failed_channels,
        subscribe=True,
        origin_boundary=FactBoundary(1, 0, 1_000, 1),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )

    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    assert reducer.option_books[name] is book
    assert book.state.name == expected_book_state
    assert reducer.tickers[name] is ticker
    assert (name in reducer._ticker_unavailable) is expected_ticker_gap
    assert reducer._next_option_catalog_recovery_ms is None
    assert not reducer.results[name].known_evaluation
    assert reducer.results[name].reason == (
        "OPTION_BOOK_UNKNOWN" if "book" in failed_channel_kinds else "OPTION_CHANNEL_FAILURE"
    )
    current = reducer.results[name].current_evaluation
    assert current is not None
    assert current.continuity_gap
    assert {
        channel for channel, slot in reducer._channels.items() if slot.retry_after_ms is not None
    } == set(failed_channels)


def test_ticker_timestamp_ahead_is_local_and_requests_one_resubscribe(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=1_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    first = make_option("BTC_USDC-27SEP24-100010-C", 1_000_000 + 60 * 60_000)
    second = make_option("BTC_USDC-27SEP24-100020-C", 1_000_000 + 60 * 60_000)
    reducer.options = {first.instrument_name: first, second.instrument_name: second}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books = {
        first.instrument_name: make_book(first.instrument_name, "1"),
        second.instrument_name: make_book(second.instrument_name, "1"),
    }
    reducer.tickers = {
        first.instrument_name: TickerState(Decimal(100), "index_price", 1_000_001),
        second.instrument_name: TickerState(Decimal(100), "index_price", 1_000_001),
    }
    reducer.trackers = {
        first.instrument_name: EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=first.instrument_name,
        ),
        second.instrument_name: EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=second.instrument_name,
        ),
    }
    first_channel = ticker_channel(first.instrument_name)
    acknowledge_channel(reducer, first_channel)
    reducer._causal_seq = 1
    reducer.settle_fact(
        boundary=FactBoundary(1, 0, 1_000, 1),
        affected_instruments=tuple(reducer.options),
        countable=True,
    )
    second_episode = reducer.trackers[second.instrument_name].episode_id
    assert second_episode is not None
    second_tracker_state = reducer.trackers[second.instrument_name].state
    second_atomic_state = reducer.atomic_states[second_episode]
    assert reducer.clock is not None
    trusted_upper = reducer.clock.interval_at(1_001).upper_ms

    assert reducer._apply_ticker(
        first.instrument_name,
        {
            "instrument_name": first.instrument_name,
            "timestamp": trusted_upper,
            "underlying_price": 100,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 0, 1_001, 2),
    )
    assert first.instrument_name not in reducer._ticker_currentness_latches
    assert reducer.tickers[first.instrument_name].source_timestamp_ms == trusted_upper

    ahead_timestamp = trusted_upper + 1
    assert not reducer._apply_ticker(
        first.instrument_name,
        {
            "instrument_name": first.instrument_name,
            "timestamp": ahead_timestamp,
            "underlying_price": 100,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 0, 1_001, 3),
    )
    reducer.settle_fact(
        boundary=FactBoundary(1, 0, 1_002, 4),
        affected_instruments=(first.instrument_name,),
        countable=False,
        observation_reason="HEARTBEAT_OR_UNRELATED_FACT",
    )

    assert reducer.results[first.instrument_name].reason == "TICKER_TIMESTAMP_AHEAD"
    assert reducer.trackers[first.instrument_name].detector_state is DetectorState.UNKNOWN
    assert reducer.trackers[second.instrument_name].episode_id == second_episode
    assert reducer.trackers[second.instrument_name].state is second_tracker_state
    assert reducer.trackers[second.instrument_name].detector_state is DetectorState.ANOMALY_ACTIVE
    assert reducer.atomic_states[second_episode] is second_atomic_state
    aggregate = next(iter(reducer.aggregate_results.values()))
    assert aggregate.state is DetectorState.ANOMALY_ACTIVE
    assert aggregate.coverage is not None and aggregate.coverage.name == "DEGRADED"
    assert reducer._coverage._current_state is CoverageState.KNOWN_DEGRADED
    assert reducer.tickers[first.instrument_name].source_timestamp_ms == trusted_upper
    assert reducer.diagnostics.option_channel_resync_count == 1
    assert (
        len(
            tuple(
                request
                for request in reducer.pending_rpcs.values()
                if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
            )
        )
        == 1
    )
    first_unsubscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": first_unsubscribe.request_id,
                "result": first_unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )
    first_subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": first_subscribe.request_id,
                "result": first_subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=2_002,
        ),
        processed_monotonic_ms=2_002,
    )
    equal_timestamp_commands = reducer.reduce(
        subscription_frame(
            first_channel,
            {
                "instrument_name": first.instrument_name,
                "timestamp": ahead_timestamp,
                "underlying_price": 100,
                "underlying_index": "index_price",
            },
            ingress_seq=3,
            received_monotonic_ms=2_003,
        ),
        processed_monotonic_ms=2_003,
    )

    assert reducer.results[first.instrument_name].reason == "TICKER_TIMESTAMP_AHEAD"
    assert reducer.trackers[first.instrument_name].detector_state is DetectorState.UNKNOWN
    assert reducer.diagnostics.option_channel_resync_count == 2
    second_unsubscribe = next(
        command
        for command in equal_timestamp_commands
        if command.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    assert (
        reducer.reduce(
            subscription_frame(
                first_channel,
                {
                    "instrument_name": first.instrument_name,
                    "timestamp": ahead_timestamp + 1,
                    "underlying_price": 100,
                    "underlying_index": "index_price",
                },
                ingress_seq=4,
                received_monotonic_ms=2_004,
            ),
            processed_monotonic_ms=2_004,
        )
        == ()
    )
    assert reducer.diagnostics.option_channel_resync_count == 2

    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": second_unsubscribe.request_id,
                "result": second_unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=5,
            received_monotonic_ms=2_005,
        ),
        processed_monotonic_ms=2_005,
    )
    second_subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": second_subscribe.request_id,
                "result": second_subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=6,
            received_monotonic_ms=2_006,
        ),
        processed_monotonic_ms=2_006,
    )
    assert reducer.clock is not None
    recovered_timestamp = reducer.clock.interval_at(2_007).upper_ms
    reducer.reduce(
        subscription_frame(
            first_channel,
            {
                "instrument_name": first.instrument_name,
                "timestamp": recovered_timestamp,
                "underlying_price": 100,
                "underlying_index": "index_price",
            },
            ingress_seq=7,
            received_monotonic_ms=2_007,
        ),
        processed_monotonic_ms=2_007,
    )

    assert reducer.results[first.instrument_name].known_evaluation
    assert reducer.results[first.instrument_name].reason is None
    assert not reducer.results[first.instrument_name].observation_eligible
    assert reducer.trackers[first.instrument_name].state.name == "ARMED"
    assert reducer.trackers[first.instrument_name].episode_id is None


def test_option_book_gap_quarantines_old_generation_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    instrument = make_option("SHORT", 1_000_000 + 60 * 60_000)
    reducer.options = {"SHORT": instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books["SHORT"] = make_book("SHORT", "1")
    reducer.tickers["SHORT"] = TickerState(Decimal(100), "index_price", 1)
    activate_directly(reducer, instrument)
    channel = book_channel("SHORT")
    acknowledge_channel(reducer, channel)

    assert not reducer._apply_book(
        "SHORT",
        {
            "type": "change",
            "timestamp": 2,
            "instrument_name": "SHORT",
            "change_id": 3,
            "prev_change_id": 99,
            "bids": [],
            "asks": [],
        },
        FactBoundary(1, 1, 1_001, 2),
    )
    assert reducer.channel_state(channel) is ChannelState.UNSUBSCRIBE_PENDING
    unsubscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": unsubscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )
    assert reducer.channel_state(channel) is ChannelState.ACKNOWLEDGED
    assert reducer._channels[channel].resync_requested

    reducer._accept_subscription_frame(
        subscription_frame(
            channel,
            {
                "type": "snapshot",
                "timestamp": 3,
                "instrument_name": "SHORT",
                "change_id": 4,
                "bids": [["new", "1", "0.1"]],
                "asks": [],
            },
            ingress_seq=2,
            received_monotonic_ms=1_002,
        )
    )

    assert reducer.option_books["SHORT"].state.name == "UNKNOWN"
    assert not reducer.results["SHORT"].known_evaluation
    assert reducer.trackers["SHORT"].episode_id is None
    assert not tuple(tmp_path.glob("short-vol-anomaly-*.json"))


def test_combo_book_gap_quarantines_old_generation_atomic_quote(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 60 * 60_000
    short = make_option("SHORT", expiry)
    long = OptionInstrument(
        "LONG",
        expiry,
        Decimal(110),
        OptionType.CALL,
        short.amount,
    )
    reducer.options = {"SHORT": short, "LONG": long}
    reducer.catalog_options = dict(reducer.options)
    episode_id = activate_directly(reducer, short)
    reducer._last_detector_causal_seq["SHORT"] = 1
    reducer._causal_seq = 1
    reducer.combos["COMBO"] = ComboInstrument(
        "COMBO",
        "active",
        (ComboLeg("SHORT", Decimal("-1")), ComboLeg("LONG", Decimal("1"))),
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    reducer.combo_catalog.complete = True
    reducer.combo_catalog.source_complete = True
    reducer.combo_books["COMBO"] = make_book("COMBO", None)
    channel = book_channel("COMBO")
    acknowledge_channel(reducer, channel)

    assert not reducer._apply_book(
        "COMBO",
        {
            "type": "change",
            "timestamp": 2,
            "instrument_name": "COMBO",
            "change_id": 3,
            "prev_change_id": 99,
            "bids": [],
            "asks": [],
        },
        FactBoundary(1, 1, 1_001, 2),
    )
    assert reducer.atomic_states[episode_id] is PublicAtomicQuoteState.UNKNOWN
    assert reducer.channel_state(channel) is ChannelState.UNSUBSCRIBE_PENDING

    reducer._accept_subscription_frame(
        subscription_frame(
            channel,
            {
                "type": "snapshot",
                "timestamp": 3,
                "instrument_name": "COMBO",
                "change_id": 4,
                "bids": [],
                "asks": [["new", "-1", "0.1"]],
            },
            ingress_seq=2,
            received_monotonic_ms=1_002,
        )
    )

    assert reducer.combo_books["COMBO"].state.name == "UNKNOWN"
    assert reducer.atomic_states[episode_id] is PublicAtomicQuoteState.UNKNOWN
    assert not tuple(tmp_path.glob("public-atomic-quote-*.json"))


def test_index_tail_pending_preserves_episode_but_disables_layer_two_current(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books[instrument.instrument_name] = make_book(
        instrument.instrument_name,
        "1",
    )
    reducer.tickers[instrument.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_001,
    )
    episode_id = activate_directly(reducer, instrument)
    reducer.atomic_states[episode_id] = PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE
    monkeypatch.setattr(
        reducer.index,
        "current_tail",
        lambda *_args, **_kwargs: IndexTail(IndexTailStatus.TIME_BOUNDARY_PENDING),
    )

    reducer.settle_fact(
        boundary=FactBoundary(1, 1, 1_001, 2),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
        observation_reason="TIME_BOUNDARY",
    )

    assert reducer.trackers[instrument.instrument_name].episode_id == episode_id
    assert reducer.trackers[instrument.instrument_name].state.name == "INDEX_TAIL_PENDING"
    assert reducer.atomic_states[episode_id] is PublicAtomicQuoteState.NOT_EVALUATED


def test_combo_subscribe_failure_only_makes_layer_two_unknown(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 60 * 60_000
    short = make_option("SHORT", expiry)
    long = OptionInstrument(
        "LONG",
        expiry,
        Decimal("110"),
        OptionType.CALL,
        short.amount,
    )
    reducer.options = {"SHORT": short, "LONG": long}
    reducer.catalog_options = dict(reducer.options)
    episode_id = activate_directly(reducer, short)
    reducer.combos["COMBO"] = ComboInstrument(
        "COMBO",
        "active",
        (ComboLeg("SHORT", Decimal("-1")), ComboLeg("LONG", Decimal("1"))),
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    reducer.combo_catalog.complete = True
    reducer.atomic_states[episode_id] = PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE
    reducer._sync_combo_subscriptions(FactBoundary(1, 0, 1_000, 1))
    subscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )

    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    assert reducer.trackers["SHORT"].detector_state is DetectorState.ANOMALY_ACTIVE
    assert reducer.trackers["SHORT"].episode_id == episode_id
    assert reducer.atomic_states[episode_id] is PublicAtomicQuoteState.UNKNOWN
    assert not reducer.combo_catalog.complete


def test_membership_sync_retries_missing_desired_option_channels(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.catalog_options = {instrument.instrument_name: instrument}
    reducer.options = {instrument.instrument_name: instrument}
    reducer.trackers[instrument.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=instrument.instrument_name,
    )

    reducer._sync_membership(FactBoundary(1, 0, 1_000, 1))
    subscriptions = tuple(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )

    assert len(subscriptions) == 2
    requested: set[str] = set()
    for request in subscriptions:
        channels = request.params.get("channels")
        assert isinstance(channels, list)
        assert all(isinstance(channel, str) for channel in channels)
        requested.update(channels)
    assert requested == {
        ticker_channel(instrument.instrument_name),
        book_channel(instrument.instrument_name),
        "deribit_price_index.btc_usdc",
    }


def test_combo_lifecycle_immediately_invalidates_old_layer_two_negative(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    episode_id = activate_directly(reducer, instrument)
    reducer.combo_catalog.complete = True
    reducer.combo_catalog.source_complete = True
    reducer.atomic_states[episode_id] = PublicAtomicQuoteState.NO_ACTIVE_COMBO

    reducer._apply_combo_lifecycle(
        {"instrument_name": "NEW-COMBO", "state": "open"},
        FactBoundary(1, 1, 1_001, 2),
    )

    assert not reducer.combo_catalog.complete
    assert reducer.atomic_states[episode_id] is PublicAtomicQuoteState.UNKNOWN


def test_temporary_protective_leg_lifecycle_is_scope_local_atomic_unknown(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    first_expiry = 1_000_000 + 60 * 60_000
    second_expiry = first_expiry + 60_000
    short = make_option("SHORT", first_expiry)
    locked_wing = OptionInstrument(
        "LOCKED-WING",
        first_expiry,
        Decimal("110"),
        OptionType.CALL,
        short.amount,
    )
    unrelated = make_option("UNRELATED", second_expiry)
    reducer.options = {
        "SHORT": short,
        "LOCKED-WING": locked_wing,
        "UNRELATED": unrelated,
    }
    reducer.catalog_options = dict(reducer.options)
    reducer.combo_catalog.complete = True
    reducer._option_lifecycle_unavailable["LOCKED-WING"] = "OPTION_LIFECYCLE_LOCKED"
    short_episode = activate_directly(reducer, short)
    unrelated_episode = activate_directly(reducer, unrelated)

    reducer._evaluate_atomic(reducer.trackers["SHORT"])
    reducer._evaluate_atomic(reducer.trackers["UNRELATED"])

    assert reducer.atomic_states[short_episode] is PublicAtomicQuoteState.UNKNOWN
    assert reducer.atomic_states[unrelated_episode] is PublicAtomicQuoteState.NO_ACTIVE_COMBO


def test_one_option_subscribe_failure_is_local_to_that_instrument(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("FIRST", expiry)
    second = make_option("SECOND", expiry)
    reducer.options = {"FIRST": first, "SECOND": second}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books["FIRST"] = ContinuousOrderBook("FIRST")
    first_episode = activate_directly(reducer, first)
    second_episode = activate_directly(reducer, second)
    assert reducer.clock is not None
    reducer._last_time_currentness_token = reducer._time_currentness_token(
        reducer.clock.interval_at(1_001)
    )
    reducer._plan_channel_change(
        ("book.FIRST.100ms",),
        subscribe=True,
        origin_boundary=FactBoundary(1, 0, 1_000, 1),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )

    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    assert reducer.trackers["FIRST"].episode_id is None
    assert reducer.trackers["FIRST"].detector_state is DetectorState.UNKNOWN
    assert reducer.trackers["SECOND"].episode_id == second_episode
    assert reducer.trackers["SECOND"].detector_state is DetectorState.ANOMALY_ACTIVE
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 1
    assert first_episode != second_episode


def test_band_suspension_duration_uses_monotonic_boundaries(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option("SHORT", 1_000_000 + 60 * 60_000)
    reducer.options = {"SHORT": instrument}
    reducer.catalog_options = dict(reducer.options)
    activate_directly(reducer, instrument)
    reducer.trackers["SHORT"].suspend_for_band_boundary()

    reducer._update_coverage(1_000)
    reducer._update_coverage(1_500)
    reducer.trackers["SHORT"].resume_after_band_boundary()
    reducer._update_coverage(2_000)

    assert reducer._band_suspended_duration_ms == 1_000


def test_noncountable_known_current_advances_active_duration_without_persistence(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    instrument = make_option("BTC_USDC-27SEP24-100010-C", 1_000_000 + 60 * 60_000)
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books[instrument.instrument_name] = make_book(instrument.instrument_name, "1")
    reducer.tickers[instrument.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_001,
    )
    episode_id = activate_directly(reducer, instrument)
    reducer._episode_started_ms[episode_id] = 1_000
    reducer._episode_last_trusted_ms[episode_id] = 1_000
    reducer._episode_option_type[episode_id] = OptionType.CALL

    reducer.settle_fact(
        boundary=FactBoundary(1, 1, 1_500, 2),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
        observation_reason="ASK_ONLY",
    )
    assert reducer.results[instrument.instrument_name].known_evaluation
    assert not reducer.results[instrument.instrument_name].observation_eligible
    assert reducer.trackers[instrument.instrument_name].episode_id == episode_id

    reducer.index.gap()
    reducer.settle_fact(
        boundary=FactBoundary(1, 2, 2_000, 3),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
        observation_reason="INDEX_GAP",
    )

    assert reducer._known_active_duration_ms[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 500


def test_index_tail_pending_interval_is_excluded_from_known_active_duration(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.option_books[instrument.instrument_name] = make_book(
        instrument.instrument_name,
        "1",
    )
    reducer.tickers[instrument.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_001,
    )
    episode_id = activate_directly(reducer, instrument)
    reducer._episode_started_ms[episode_id] = 1_000
    reducer._episode_last_trusted_ms[episode_id] = 1_000
    reducer._episode_option_type[episode_id] = OptionType.CALL
    original_current_tail = reducer.index.current_tail
    monkeypatch.setattr(
        reducer.index,
        "current_tail",
        lambda *_args, **_kwargs: IndexTail(IndexTailStatus.TIME_BOUNDARY_PENDING),
    )

    reducer.settle_fact(
        boundary=FactBoundary(1, 1, 1_500, 2),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
        observation_reason="TIME_BOUNDARY",
    )
    monkeypatch.setattr(reducer.index, "current_tail", original_current_tail)
    reducer.settle_fact(
        boundary=FactBoundary(1, 2, 2_000, 3),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
        observation_reason="TIME_BOUNDARY",
    )

    transition = reducer.trackers[instrument.instrument_name].stop(causal_seq=4)
    reducer._record_episode_end(transition.ended_episode, 2_500)

    assert reducer._known_active_duration_ms[EpisodeEndReason.CENSORED_AT_STOP.value] == 1_000
