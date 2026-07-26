from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from conftest import PolicyFactory, encode_policy, policy_document
from market_monitor import ContinuousOrderBook, TimeInterval, TrustedClock
from market_monitor.deribit import PLATFORM_CHANNELS
from options_domain import (
    AmountMetadata,
    ComboInstrument,
    ComboLeg,
    OptionInstrument,
    OptionType,
)
from radar_runtime.deribit_public import InboundEnvelope
from radar_runtime.runtime import FactBoundary, FailureScope, RadarReducer, RpcPurpose
from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.black import DecimalInterval
from short_vol_radar.detector import (
    DetectorObservation,
    DetectorState,
    EpisodeEndReason,
    EpisodeTracker,
)
from short_vol_radar.evidence import EvidenceWriter
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


def test_clock_rpc_failure_invalidates_old_clock_and_schedules_fresh_bootstrap(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
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

    assert reducer.clock is None
    assert any(command.purpose is RpcPurpose.CLOCK_BOOTSTRAP for command in commands)


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
        1,
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


def test_one_option_subscribe_failure_is_local_to_that_instrument(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("FIRST", expiry)
    second = make_option("SECOND", expiry)
    reducer.options = {"FIRST": first, "SECOND": second}
    reducer.catalog_options = dict(reducer.options)
    first_episode = activate_directly(reducer, first)
    second_episode = activate_directly(reducer, second)
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
    reducer.tickers[instrument.instrument_name] = TickerState(Decimal(100), "index_price", 1)
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
