from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import radar_runtime.runtime as runtime_module
import short_vol_radar.baseline as baseline_module
from conftest import PolicyFactory, encode_policy, policy_document
from market_monitor import (
    BaselinePublicationPhase,
    ContinuityGap,
    ContinuousOrderBook,
    IndexAvailabilityState,
    IndexHistoryState,
    IndexPublicationBoundary,
    MinuteClose,
    PublishedIndexTail,
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
    PriceTickMetadata,
)
from radar_runtime.deribit_public import (
    InboundEnvelope,
    PublicSessionError,
    SendControlEvent,
    SendControlKind,
)
from radar_runtime.funnel import FunnelTracker
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    ChannelState,
    FactBoundary,
    FailureScope,
    RadarReducer,
    RpcPurpose,
    ScopeSnapshot,
)
from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.baseline import BaselineStatistics
from short_vol_radar.black import DecimalInterval, black_price
from short_vol_radar.bucket import (
    BucketConfirmationResetReason,
    RadarBucketEpisodeTracker,
    RadarBucketTrackerTransition,
)
from short_vol_radar.detector import (
    DetectorCoverage,
    DetectorObservation,
    DetectorState,
    EpisodeEndReason,
    EpisodeTracker,
    ObservationSignal,
    TrackerState,
    TrackerTransition,
)
from short_vol_radar.evidence import (
    CoverageState,
    EvidenceError,
    RadarEventSink,
)
from short_vol_radar.policy import RadarPolicy, load_policy_bytes
from short_vol_radar.radar import (
    CurrentDisposition,
    CurrentEvaluation,
    DeltaBucket,
    EvaluationResult,
    TickerState,
)
from short_vol_radar.review import build_score_feature_contexts
from short_vol_radar.score import (
    LeaderCoverage,
    RadarBucketKey,
    RadarScoreInputs,
    ScoreBand,
    ScoreFactorName,
    build_radar_score_packet,
    compute_radar_score,
    compute_unsigned_oi_concentration,
)

TEST_RUNTIME_IDENTITY = "sha256:" + "b" * 64


def make_reducer(tmp_path: Path, policy: RadarPolicy) -> RadarReducer:
    reducer = RadarReducer(
        policy=policy,
        code_identity="a" * 40,
        event_sink=RadarEventSink(
            code_identity="a" * 40,
            runtime_identity=TEST_RUNTIME_IDENTITY,
            policy_identity=policy.identity,
        ),
        runtime_identity=TEST_RUNTIME_IDENTITY,
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


def fact_commit(
    boundary: FactBoundary,
    cause: CausalCause,
    *,
    failure_domain: FailureScope = FailureScope.CLOCK_INDEX,
    affected_scopes: tuple[str, ...] = ("GLOBAL",),
) -> CausalCommit:
    return CausalCommit(
        boundary=boundary,
        cause=cause,
        failure_domain=failure_domain,
        affected_scopes=affected_scopes,
    )


TEST_PRICE_TICK = PriceTickMetadata(Decimal("0.00000001"))


def make_option(name: str, expiry_ms: int, *, amount_known: bool = True) -> OptionInstrument:
    return OptionInstrument(
        name,
        expiry_ms,
        Decimal("100.01"),
        OptionType.CALL,
        (AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")) if amount_known else None),
        TEST_PRICE_TICK,
    )


def make_book(name: str, price: str | None) -> ContinuousOrderBook:
    book = ContinuousOrderBook(name)
    bid = None if price is None else Decimal(price) / Decimal(100)
    asks = [] if bid is None else [["new", bid + Decimal("0.00000002"), "0.1"]]
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": name,
            "change_id": 1,
            "bids": [] if bid is None else [["new", bid, "0.1"]],
            "asks": asks,
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


def complete_rpc_send(
    reducer: RadarReducer,
    request: object,
    *,
    ingress_seq: int,
) -> None:
    del ingress_seq
    assert isinstance(request, runtime_module.PendingRpc)
    sent_ms = request.origin_boundary.received_monotonic_ms
    reducer.reduce(
        InboundEnvelope(
            {},
            session_epoch=request.session_epoch,
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=sent_ms,
            control_event=SendControlEvent(
                kind=SendControlKind.SEND_COMPLETED,
                request_id=request.request_id,
                boundary_monotonic_ms=sent_ms,
            ),
        ),
        processed_monotonic_ms=sent_ms,
    )


def seed_available_index(reducer: RadarReducer) -> None:
    reducer.index_history.apply_chart_result([[300_000, 100], [600_000, 100]])
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
    reducer.index_history.apply_chart_result([[300_000, 100], [600_000, 100]])
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


def configure_full_formula_scope(
    reducer: RadarReducer,
    instrument: OptionInstrument,
    *,
    ticker_source_timestamp_ms: int = 1_000_000,
) -> None:
    total_volatility = 0.5 * math.sqrt(60 / (365 * 24 * 60))
    bid = Decimal(
        str(
            black_price(
                100,
                float(instrument.strike),
                total_volatility,
                instrument.option_type,
            )
        )
    )
    reducer.options = {instrument.instrument_name: instrument}
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[instrument.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=instrument.instrument_name,
    )
    reducer.option_books[instrument.instrument_name] = make_book(
        instrument.instrument_name,
        str(bid),
    )
    reducer.tickers[instrument.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        ticker_source_timestamp_ms,
    )


def establish_joint_witness(
    reducer: RadarReducer,
    instrument: OptionInstrument,
    *,
    monotonic_ms: int = 1_001,
) -> None:
    seed_flat_available_index(reducer)
    configure_full_formula_scope(reducer, instrument)
    reducer._causal_seq = 1
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, monotonic_ms, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=True,
    )
    assert reducer.results[instrument.instrument_name].full_formula_evaluation
    assert reducer.latest_funnel_causal_seq == 1
    assert len(reducer.latest_funnel_evaluations) == 1
    assert reducer.latest_funnel_evaluations[0].instrument_name == instrument.instrument_name
    assert reducer.latest_funnel_evaluations[0].known_evaluation


def activate_directly(
    reducer: RadarReducer,
    instrument: OptionInstrument,
    *,
    band_index: int = 0,
) -> str:
    band = reducer.policy.tte_bands[band_index]
    rule = band.option_rules[instrument.option_type]
    used_delta_buckets = {
        key.delta_bucket
        for key in reducer.bucket_trackers
        if key.expiry_ms == instrument.expiration_timestamp_ms
        and key.option_type is instrument.option_type
    }
    delta_bucket = next(
        candidate
        for candidate in (
            DeltaBucket.NEAR_ATM_30_40,
            DeltaBucket.ATM_GT_40,
            DeltaBucket.WING_15_30,
            DeltaBucket.TAIL_05_15,
            DeltaBucket.EXTREME_TAIL_LT_05,
        )
        if candidate.value not in used_delta_buckets
    )
    bucket_key = RadarBucketKey(
        tte_band_id=band.band_id,
        expiry_ms=instrument.expiration_timestamp_ms,
        option_type=instrument.option_type,
        delta_bucket=delta_bucket.value,
    )
    score_result = compute_radar_score(
        reducer.policy.score_model,
        RadarScoreInputs(
            stressed_richness=DecimalInterval(Decimal("1.30"), Decimal("1.31")),
            stressed_executable_bid_iv=DecimalInterval(Decimal("0.49"), Decimal("0.51")),
            local_same_type_mark_iv=Decimal("0.40"),
            surface_source_skew_ms=0,
            current_expiry_atm_mark_iv=Decimal("0.50"),
            adjacent_expiry_atm_mark_iv=Decimal("0.40"),
            term_source_skew_ms=0,
            adverse_semivariance_share=DecimalInterval(Decimal(0), Decimal(0)),
            jump_share=DecimalInterval(Decimal(0), Decimal(0)),
            target_spread_ticks=DecimalInterval(Decimal(1), Decimal(1)),
            bid_consumed_level_count=2,
            ask_consumed_level_count=2,
        ),
    )
    score_result = replace(score_result, band=ScoreBand.HIGH)
    packet = build_radar_score_packet(
        policy_identity=reducer.policy.identity,
        fact_boundary={
            "code_identity": reducer.code_identity,
            "runtime_identity": reducer.runtime_identity,
            "session_epoch": 1,
            "ingress_seq": 0,
            "received_monotonic_ms": 1_000,
            "causal_seq": 1,
        },
        bucket_key=bucket_key,
        leader_instrument_name=instrument.instrument_name,
        result=score_result,
        oi_diagnostic=compute_unsigned_oi_concentration(
            open_interest=Decimal(1),
            option_gamma=Decimal("0.01"),
            bucket_total_unsigned_gamma_weight=Decimal("0.01"),
        ),
        stressed_richness=DecimalInterval(Decimal("1.30"), Decimal("1.31")),
        leader_coverage=LeaderCoverage.COMPLETE,
    )
    bucket_tracker = RadarBucketEpisodeTracker(
        runtime_identity=reducer.runtime_identity,
        policy_identity=reducer.policy.identity,
        bucket_key=bucket_key,
        score_model=reducer.policy.score_model,
        clue_eligible=True,
    )
    separation = max(rule.minimum_separation_ms, 1)
    for index in range(rule.activation_observation_count):
        bucket_tracker.observe(
            packet=packet,
            observation_identity=("test-bucket-score", instrument.instrument_name, index),
            causal_seq=1,
            trusted_time=TimeInterval(
                1_000_000 + index * separation,
                1_000_000 + index * separation,
            ),
            rule=rule,
        )
    assert bucket_tracker.episode is not None
    reducer.bucket_trackers[bucket_key] = bucket_tracker
    reducer.score_bucket_keys[instrument.instrument_name] = bucket_key
    reducer.score_results[instrument.instrument_name] = score_result
    reducer.score_packets[instrument.instrument_name] = packet
    reducer.bucket_leader_by_key[bucket_key] = instrument.instrument_name
    reducer.bucket_leader_coverage[bucket_key] = LeaderCoverage.COMPLETE
    tracker = EpisodeTracker(
        runtime_identity=reducer.runtime_identity,
        policy_identity=reducer.policy.identity,
        instrument_name=instrument.instrument_name,
    )
    tracker.state = TrackerState.ACTIVE
    tracker.episode_id = bucket_tracker.episode.episode_identity
    tracker.activation_band_id = band.band_id
    tracker.activation_causal_seq = 1
    reducer.trackers[instrument.instrument_name] = tracker
    calculation = SimpleNamespace(
        baseline=SimpleNamespace(window_diagnostics=()),
        delta=DecimalInterval(Decimal("0.19"), Decimal("0.21")),
        delta_bucket=delta_bucket,
        delta_clue_eligible=True,
        richness=DecimalInterval(Decimal("1.30"), Decimal("1.31")),
        target_spread_ticks=Decimal(1),
        target_bid=SimpleNamespace(consumed=(object(),)),
        target_ask=SimpleNamespace(consumed=(object(),)),
        rule=rule,
        clue_eligible=True,
        score_result=score_result,
    )
    current = CurrentEvaluation(
        disposition=CurrentDisposition.V2_SCORE,
        reason=None,
        known_evaluation=True,
        full_formula_evaluation=True,
        band_id=band.band_id,
        calculation=cast(Any, calculation),
        score_result=score_result,
    )
    reducer.results[instrument.instrument_name] = EvaluationResult(
        detector_state=DetectorState.ANOMALY_ACTIVE,
        reason=None,
        known_evaluation=True,
        full_formula_evaluation=True,
        band_id=band.band_id,
        transition=TrackerTransition(),
        calculation=cast(Any, calculation),
        current_evaluation=current,
        score_result=score_result,
        score_packet=packet,
    )
    return bucket_tracker.episode.episode_identity


def test_band_boundary_suspension_resets_partial_detector_persistence(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=2, separation_ms=0)
    rule = load_policy_bytes(exact, digest).tte_bands[0].option_rules[OptionType.CALL]
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    first = tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(1_000, 1_000),
            band_id="band",
            signal=ObservationSignal.ACTIVATE,
        ),
        rule,
    )
    assert first.activated_episode_id is None

    tracker.suspend_for_band_boundary()
    tracker.resume_after_band_boundary()
    second = tracker.observe(
        DetectorObservation(
            causal_seq=2,
            trusted_time=TimeInterval(2_000, 2_000),
            band_id="band",
            signal=ObservationSignal.ACTIVATE,
        ),
        rule,
    )

    assert second.activated_episode_id is None
    assert tracker.state is TrackerState.ARMED


def test_one_global_index_gap_makes_every_instrument_unknown_in_same_fact_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("BTC-27SEP24-100010-C", expiry)
    second = make_option("BTC-27SEP24-100020-C", expiry)
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
    seed_flat_available_index(reducer)
    assert not reducer._apply_index(
        {"timestamp": 500_000, "price": 100, "index_name": "btc_usd"},
        FactBoundary(1, 1, 1_001, 2),
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
        "BTC-27SEP24-100010-C",
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
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=True,
    )
    assert reducer.results[instrument.instrument_name].known_evaluation
    assert reducer._coverage._current_state.value == CoverageState.KNOWN_COMPLETE.value

    assert not reducer._apply_index(
        {
            "timestamp": 900_000,
            "price": 100,
            "index_name": "btc_usd",
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


def test_non_index_boundary_seals_ready_index_minute_before_tail_classification(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    reducer.clock = TrustedClock.from_response(
        1_019_998,
        1_000,
        1_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.index.start_continuous_coverage(600_000)
    for causal_seq, timestamp in enumerate(
        (600_001, 660_000, 720_000, 780_000, 840_000, 900_000, 960_001),
        start=1,
    ):
        reducer.index.accept_tick(
            source_timestamp_ms=timestamp,
            price=100,
            causal_seq=causal_seq,
        )
        reducer.index.seal_ready(timestamp)
    reducer.index.accept_tick(
        source_timestamp_ms=1_020_000,
        price=100,
        causal_seq=8,
    )
    reducer.index_history.apply_chart_result([[300_000, 100], [600_000, 100]])
    instrument = make_option(
        "BTC-08AUG26-100000-C",
        1_020_000 + 60 * 60_000,
    )
    configure_full_formula_scope(
        reducer,
        instrument,
        ticker_source_timestamp_ms=1_019_999,
    )
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_000, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=True,
    )
    assert reducer.results[instrument.instrument_name].known_evaluation
    epoch_before = reducer._global_continuity_epoch

    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 1_003, 2),
            CausalCause.OPTION_BOOK_FACT,
            failure_domain=FailureScope.OPTION,
            affected_scopes=(f"OPTION:{instrument.instrument_name}",),
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )

    assert reducer.index.sealed[-1].minute_start_ms == 960_000
    assert reducer.results[instrument.instrument_name].known_evaluation
    assert reducer.results[instrument.instrument_name].reason != "INDEX_WINDOW_GAP"
    assert reducer._global_continuity_epoch == epoch_before
    assert reducer._active_continuity_incident is None


def test_bootstrap_warmup_does_not_report_or_recover_a_real_index_gap(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    configure_full_formula_scope(reducer, instrument)

    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.BOOTSTRAP,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )

    assert reducer.results[instrument.instrument_name].reason == "INDEX_HISTORY_BOOTSTRAP_REQUIRED"
    assert not reducer._index_gap_active
    assert not reducer._index_resubscribe_pending


def test_funnel_partitions_the_real_reducer_index_tail_at_first_availability(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    configure_full_formula_scope(reducer, instrument)
    tracker = FunnelTracker()

    warmup_commit = fact_commit(
        FactBoundary(1, 1, 1_001, 1),
        CausalCause.INDEX_TICK,
    )
    reducer.settle_fact(
        commit=warmup_commit,
        affected_instruments=(instrument.instrument_name,),
        countable=True,
    )
    assert reducer.results[instrument.instrument_name].reason == "INDEX_HISTORY_BOOTSTRAP_REQUIRED"
    tracker.observe(reducer=reducer, commit=warmup_commit, new_shadow_records=())
    warmup = tracker.snapshot().radar_knownness
    assert warmup.startup_warmup.applicable_market_scope_count == 1
    assert warmup.post_warmup.applicable_market_scope_count == 0

    seed_flat_available_index(reducer)
    available_commit = fact_commit(
        FactBoundary(1, 2, 1_002, 2),
        CausalCause.INDEX_TICK,
    )
    reducer.settle_fact(
        commit=available_commit,
        affected_instruments=(instrument.instrument_name,),
        countable=True,
    )
    assert reducer.results[instrument.instrument_name].known_evaluation
    tracker.observe(reducer=reducer, commit=available_commit, new_shadow_records=())
    knownness = tracker.snapshot().radar_knownness
    assert knownness.post_warmup.applicable_market_scope_count == 1
    assert knownness.post_warmup.radar_known_count == 1
    assert knownness.warmed_band_ids == (reducer.policy.tte_bands[0].band_id,)


def setup_same_millisecond_watermark_phase(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> tuple[RadarReducer, OptionInstrument]:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)
    reducer.clock = TrustedClock.from_response(
        1_019_999,
        20_999,
        20_999,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer._causal_seq = 2
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 20_999, 2),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )
    reducer.clock = TrustedClock.from_response(
        1_020_000,
        21_000,
        21_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer._causal_seq = 3
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 3, 21_000, 3),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )
    assert reducer.index.publication_phase is BaselinePublicationPhase.WATERMARK_PENDING
    return reducer, instrument


def test_persistent_history_window_gap_stays_radar_local_without_live_resubscribe(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    configure_full_formula_scope(reducer, instrument)
    reducer.index.start_continuous_coverage(0)
    monkeypatch.setattr(
        reducer.index_history,
        "current_tail",
        lambda *_args, **_kwargs: IndexHistoryState(
            availability=IndexAvailabilityState.WINDOW_GAP,
            reason="INDEX_HISTORY_WINDOW_GAP",
        ),
    )

    reducer._causal_seq = 1
    assert reducer._apply_index(
        {
            "timestamp": 1_000_000,
            "price": 100,
            "index_name": "btc_usd",
        },
        FactBoundary(1, 1, 1_001, 1),
    )
    assert reducer._global_continuity_epoch == 1
    assert not reducer._index_resubscribe_pending
    assert reducer.results[instrument.instrument_name].reason == "INDEX_HISTORY_WINDOW_GAP"
    assert reducer._coverage._current_state is CoverageState.UNKNOWN

    reducer._causal_seq = 2
    assert reducer._apply_index(
        {
            "timestamp": 1_000_001,
            "price": 100,
            "index_name": "btc_usd",
        },
        FactBoundary(1, 2, 1_002, 2),
    )
    assert reducer._global_continuity_epoch == 1
    assert not reducer._index_resubscribe_pending


def test_countable_history_tuple_is_observed_once_without_live_index_backfill(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=10,
        separation_ms=0,
        ticker_source_stale_deadline_ms=300_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    configure_full_formula_scope(reducer, instrument)
    name = instrument.instrument_name

    reducer._causal_seq = 1
    reducer.settle_fact(
        commit=fact_commit(FactBoundary(1, 1, 1_001, 1), CausalCause.INDEX_TICK),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.results[name].observation_eligible
    bucket_key = reducer.score_bucket_keys[name]
    bucket_tracker = reducer.bucket_trackers[bucket_key]
    assert bucket_tracker.confirmation_observation_count == 1

    reducer.index.accept_tick(source_timestamp_ms=1_020_000, price=100, causal_seq=2)
    reducer.clock = TrustedClock.from_response(
        1_020_001,
        2_000,
        2_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer._causal_seq = 2
    reducer.settle_fact(
        commit=fact_commit(FactBoundary(1, 2, 2_000, 2), CausalCause.TIME_BOUNDARY),
        affected_instruments=(name,),
        countable=False,
    )
    assert not reducer.results[name].observation_eligible
    assert bucket_tracker.confirmation_observation_count == 1
    noncountable_identity = reducer._last_observation_identity[name]

    reducer._causal_seq = 3
    reducer.settle_fact(
        commit=fact_commit(FactBoundary(1, 3, 2_001, 3), CausalCause.INDEX_TICK),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.results[name].observation_eligible
    assert reducer._last_observation_identity[name] != noncountable_identity
    assert bucket_tracker.confirmation_observation_count == 2

    for causal_seq, timestamp in enumerate(
        (1_080_000, 1_140_000, 1_200_000),
        start=4,
    ):
        reducer.index.accept_tick(
            source_timestamp_ms=timestamp,
            price=100,
            causal_seq=causal_seq,
        )
    reducer.clock = TrustedClock.from_response(
        1_200_001,
        3_000,
        3_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.index_history.apply_chart_result([[300_000, 100], [600_000, 100], [900_000, 100]])
    reducer._causal_seq = 7
    reducer.settle_fact(
        commit=fact_commit(FactBoundary(1, 4, 3_000, 7), CausalCause.INDEX_HISTORY),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.results[name].observation_eligible
    assert bucket_tracker.confirmation_observation_count == 3

    reducer._causal_seq = 8
    reducer.settle_fact(
        commit=fact_commit(FactBoundary(1, 5, 3_001, 8), CausalCause.INDEX_TICK),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.results[name].observation_eligible
    assert bucket_tracker.confirmation_observation_count == 3


def test_reducer_projects_bounded_confirmation_reset_counts_into_funnel(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    reducer._record_bucket_tracker_transition(
        RadarBucketTrackerTransition(
            confirmation_reset_reason=BucketConfirmationResetReason.LEADER_CHANGE
        ),
        1_000,
    )
    reducer._record_bucket_tracker_transition(RadarBucketTrackerTransition(), 1_001)
    reducer._latest_funnel_causal_seq = 1
    reducer._latest_funnel_evaluations = ()
    commit = fact_commit(FactBoundary(1, 1, 1_001, 1), CausalCause.TIME_BOUNDARY)
    funnel = FunnelTracker()

    funnel.observe(reducer=reducer, commit=commit, new_shadow_records=())

    assert reducer.confirmation_reset_counts == {"LEADER_CHANGE": 1}
    assert funnel.snapshot().radar_confirmation.reset_counts == {"LEADER_CHANGE": 1}


def shifted_publication_tail(
    tail: PublishedIndexTail,
    *,
    minute_start_ms: int,
    sequence: int,
    monotonic_ms: int,
) -> PublishedIndexTail:
    return replace(
        tail,
        closes=(MinuteClose(minute_start_ms, Decimal(100), sequence),),
        published_end_ms=minute_start_ms + 60_000,
        published_tail_last_minute_start_ms=minute_start_ms,
        first_publish_boundary=IndexPublicationBoundary(
            session_epoch=1,
            ingress_seq=sequence,
            received_monotonic_ms=monotonic_ms,
            causal_seq=sequence,
        ),
        proof_lower_ms=minute_start_ms + 60_000,
        proof_watermark_ms=minute_start_ms + 60_000,
    )


def test_clock_refresh_failure_keeps_fresh_clock_until_real_stale_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    reducer.pending_rpcs.clear()
    seed_available_index(reducer)
    instrument = make_option(
        "BTC-27SEP24-100010-C",
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

    complete_rpc_send(reducer, request, ingress_seq=1)
    commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": request.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    assert commands == ()
    assert reducer.clock is not None
    assert reducer.index.sealed == sealed_before_failure
    assert reducer.trackers[instrument.instrument_name].episode_id == episode_id
    assert reducer._next_clock_refresh_ms == (
        1_001 + reducer.policy.runtime_limits.time_boundary_poll_interval_ms
    )

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
    instrument = make_option("BTC-27SEP24-100010-C", expiry)
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
    complete_rpc_send(reducer, refresh, ingress_seq=1)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": refresh.request_id,
                "result": 1_000_100,
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=1_100,
        ),
        processed_monotonic_ms=1_100,
    )

    assert reducer.trackers[instrument.instrument_name].episode_id is None
    assert reducer._episode_end_counts[EpisodeEndReason.MEMBERSHIP_LOSS.value] == 1


def test_negative_platform_guard_ends_episode_once_as_session_gap(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
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
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 0


def test_subscription_evidence_failure_is_not_reclassified_as_public_payload(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))

    def fail_evidence_write(*_args: object) -> bool:
        raise EvidenceError("injected local evidence failure")

    monkeypatch.setattr(reducer, "_apply_book", fail_evidence_write)
    channel = "book.BTC-2AUG26-63000-C.agg2"
    acknowledge_channel(reducer, channel)

    with pytest.raises(EvidenceError, match="local evidence failure"):
        reducer.reduce(
            subscription_frame(
                channel,
                {},
                ingress_seq=1,
                received_monotonic_ms=1_001,
            ),
            processed_monotonic_ms=1_001,
        )


def test_subscription_does_not_relabel_business_value_error_as_public_payload(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option("BTC-2AUG26-63000-C", 10_000_000)
    reducer.options = {instrument.instrument_name: instrument}
    channel = f"ticker.{instrument.instrument_name}.agg2"
    acknowledge_channel(reducer, channel)

    def fail_business_settlement(*_args: object) -> bool:
        raise ValueError("injected business calculation failure")

    monkeypatch.setattr(reducer, "_apply_ticker", fail_business_settlement)
    with pytest.raises(ValueError, match="injected business calculation failure"):
        reducer._apply_acknowledged_subscription(
            InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "subscription",
                    "params": {
                        "channel": channel,
                        "data": {},
                    },
                },
                session_epoch=1,
                ingress_seq=1,
                received_monotonic_ms=1_000,
            )
        )


def test_final_window_time_poll_ends_whole_scope_without_market_update(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 30 * 60_000 + 500
    first = make_option("BTC-27SEP24-100010-C", expiry)
    second = make_option("BTC-27SEP24-100020-C", expiry)
    reducer.options = {first.instrument_name: first, second.instrument_name: second}
    reducer.catalog_options = dict(reducer.options)
    first_episode = activate_directly(reducer, first)
    second_episode = activate_directly(reducer, second)

    reducer.advance_time(1_600)

    assert reducer.trackers[first.instrument_name].episode_id is None
    assert reducer.trackers[second.instrument_name].episode_id is None
    assert reducer._episode_end_counts[EpisodeEndReason.MEMBERSHIP_LOSS.value] == 2
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
    first = make_option("BTC-27SEP24-100010-C", expiry)
    second = make_option("BTC-27SEP24-100020-C", expiry)
    reducer.options = {first.instrument_name: first, second.instrument_name: second}
    reducer.catalog_options = dict(reducer.options)
    activate_directly(reducer, first, band_index=1)
    activate_directly(reducer, second, band_index=1)

    reducer.advance_time(1_600)

    assert reducer.trackers[first.instrument_name].episode_id is None
    assert reducer.trackers[second.instrument_name].episode_id is None
    assert reducer._episode_end_counts[EpisodeEndReason.MEMBERSHIP_LOSS.value] == 2


def test_amount_unknown_to_valid_establishes_known_current_without_activation_count(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    unknown = make_option("BTC-27SEP24-100010-C", expiry, amount_known=False)
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
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(unknown.instrument_name,),
        countable=True,
    )
    assert reducer.trackers[unknown.instrument_name].detector_state is DetectorState.UNKNOWN
    assert reducer.latest_funnel_causal_seq == 1
    assert len(reducer.latest_funnel_evaluations) == 1
    assert not reducer.latest_funnel_evaluations[0].known_evaluation
    assert reducer.latest_funnel_evaluations[0].reason == "OPTION_AMOUNT_METADATA_UNKNOWN"

    valid = make_option(unknown.instrument_name, expiry, amount_known=True)
    reducer.options[valid.instrument_name] = valid
    reducer.catalog_options[valid.instrument_name] = valid
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 1_002, 2),
            CausalCause.OPTION_METADATA,
            failure_domain=FailureScope.OPTION_CATALOG,
            affected_scopes=("GLOBAL",),
        ),
        affected_instruments=(valid.instrument_name,),
        countable=False,
    )

    result = reducer.results[valid.instrument_name]
    assert result.known_evaluation
    assert not result.observation_eligible
    assert reducer.latest_funnel_causal_seq == 2
    assert not reducer.latest_funnel_evaluations
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
    valid = make_option("BTC-27SEP24-100010-C", expiry)
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
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.OPTION_METADATA,
            failure_domain=FailureScope.OPTION_CATALOG,
        ),
        affected_instruments=(missing.instrument_name,),
        countable=False,
    )

    assert reducer.trackers[missing.instrument_name].episode_id is None
    assert episode_id not in reducer.atomic_states
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1


def test_late_ticker_snapshot_is_shape_valid_and_has_no_truth_side_effects(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=300_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)
    name = instrument.instrument_name
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel, generation=7)
    reducer._ticker_generations[name] = 7
    accepted = reducer.tickers[name]
    episode_id = reducer.trackers[name].episode_id
    assert episode_id is not None
    result = reducer.results[name]
    coverage_state = reducer._coverage._current_state
    coverage_start = reducer._coverage._current_start_ms
    anomaly_events = reducer.event_sink.anomalies

    assert (
        reducer.reduce(
            subscription_frame(
                channel,
                {
                    "instrument_name": name,
                    "timestamp": accepted.source_timestamp_ms - 1,
                    "underlying_price": 99,
                    "underlying_index": "index_price",
                },
                ingress_seq=1,
                received_monotonic_ms=1_002,
            ),
            processed_monotonic_ms=1_002,
        )
        == ()
    )

    assert reducer.tickers[name] is accepted
    assert reducer.results[name].detector_state is result.detector_state
    assert reducer.results[name].known_evaluation == result.known_evaluation
    assert reducer.results[name].full_formula_evaluation == result.full_formula_evaluation
    assert reducer.trackers[name].episode_id == episode_id
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 0
    assert reducer._coverage._current_state is coverage_state
    assert reducer._coverage._current_start_ms == coverage_start
    assert reducer.event_sink.anomalies == anomaly_events
    assert not reducer._channels[channel].resync_requested


def test_equal_ticker_timestamp_applies_in_later_ingress_order(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    establish_joint_witness(reducer, instrument)
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel, generation=3)
    accepted_timestamp = reducer.tickers[name].source_timestamp_ms

    reducer.reduce(
        subscription_frame(
            channel,
            {
                "instrument_name": name,
                "timestamp": accepted_timestamp,
                "underlying_price": 101,
                "underlying_index": "index_price",
            },
            ingress_seq=1,
            received_monotonic_ms=1_002,
        ),
        processed_monotonic_ms=1_002,
    )

    assert reducer.tickers[name] == TickerState(
        Decimal(101),
        "index_price",
        accepted_timestamp,
    )


def test_older_ticker_is_late_ignored_even_when_candidate_timestamp_is_ahead(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC-27SEP24-100010-C"
    establish_joint_witness(
        reducer,
        make_option(name, 1_000_000 + 60 * 60_000),
    )
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel, generation=9)
    reducer._ticker_generations[name] = 9
    accepted = reducer.tickers[name]
    reducer.clock = TrustedClock.from_response(
        accepted.source_timestamp_ms - 100,
        2_000,
        2_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )

    reducer.reduce(
        subscription_frame(
            channel,
            {
                "instrument_name": name,
                "timestamp": accepted.source_timestamp_ms - 1,
                "underlying_price": 99,
                "underlying_index": "index_price",
            },
            ingress_seq=1,
            received_monotonic_ms=2_000,
        ),
        processed_monotonic_ms=2_000,
    )

    assert reducer.tickers[name] is accepted


def test_ticker_candidate_without_trusted_time_is_not_classified_current(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC-27SEP24-100010-C"
    reducer.options[name] = make_option(name, 1_000_000 + 60 * 60_000)
    acknowledge_channel(reducer, ticker_channel(name), generation=2)
    reducer.clock = None

    assert reducer._apply_ticker(
        name,
        {
            "instrument_name": name,
            "timestamp": 1_000_000,
            "underlying_price": 100,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 1, 1_001, 1),
    )

    assert reducer._coverage._current_state is CoverageState.UNKNOWN
    assert reducer._global_continuity_epoch == 1


@pytest.mark.parametrize(
    ("delta", "mark_iv", "open_interest", "gamma", "expected_countable"),
    [
        ("0.25", "50", "11", "0.02", False),
        ("0.26", "50", "10", "0.01", True),
        ("0.25", "51", "10", "0.01", True),
    ],
)
def test_ticker_countability_tracks_score_inputs_but_not_oi_diagnostics(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
    delta: str,
    mark_iv: str,
    open_interest: str,
    gamma: str,
    expected_countable: bool,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC-27SEP24-100010-C"
    reducer.options[name] = make_option(name, 1_000_000 + 60 * 60_000)
    reducer.tickers[name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_000,
        signed_delta=Decimal("0.25"),
        mark_iv_fraction=Decimal("0.50"),
        open_interest=Decimal(10),
        option_gamma=Decimal("0.01"),
    )
    countability: list[bool] = []

    def capture_boundary(
        _instrument_name: str,
        *,
        boundary: FactBoundary,
        cause: CausalCause,
        countable: bool,
    ) -> None:
        assert boundary.causal_seq == 1
        assert cause is CausalCause.TICKER_APPLIED
        countability.append(countable)

    monkeypatch.setattr(reducer, "_settle_ticker_boundary", capture_boundary)

    assert reducer._apply_ticker(
        name,
        {
            "instrument_name": name,
            "timestamp": 1_000_001,
            "underlying_price": 100,
            "underlying_index": "index_price",
            "greeks": {"delta": delta, "gamma": gamma},
            "mark_iv": mark_iv,
            "open_interest": open_interest,
        },
        FactBoundary(1, 1, 1_001, 1),
    )

    assert countability == [expected_countable]


def test_cross_sectional_ticker_dependency_includes_call_put_and_immediately_shorter_expiry(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    previous_expiry = 1_000_000 + 30 * 60_000
    current_expiry = 1_000_000 + 60 * 60_000
    next_expiry = 1_000_000 + 120 * 60_000
    far_expiry = 1_000_000 + 240 * 60_000
    current_call = make_option("CURRENT-C", current_expiry)
    current_put = replace(make_option("CURRENT-P", current_expiry), option_type=OptionType.PUT)
    previous_put = replace(
        make_option("PREVIOUS-P", previous_expiry),
        option_type=OptionType.PUT,
    )
    next_call = make_option("NEXT-C", next_expiry)
    far_put = replace(make_option("FAR-P", far_expiry), option_type=OptionType.PUT)
    reducer.options = {
        option.instrument_name: option
        for option in (current_call, current_put, previous_put, next_call, far_put)
    }

    assert reducer._cross_sectional_score_dependents((current_call.instrument_name,)) == (
        "CURRENT-C",
        "CURRENT-P",
        "PREVIOUS-P",
    )


def test_cross_sectional_ticker_change_reuses_peer_core_and_refreshes_term_score(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    previous_expiry = 1_000_000 + 60 * 60_000
    current_expiry = 1_000_000 + 120 * 60_000
    instruments = (
        make_option("PREVIOUS-ATM", previous_expiry),
        replace(make_option("PREVIOUS-WING", previous_expiry), strike=Decimal("100.02")),
        make_option("CURRENT-ATM", current_expiry),
        replace(make_option("CURRENT-WING", current_expiry), strike=Decimal("100.02")),
    )
    reducer.options = {instrument.instrument_name: instrument for instrument in instruments}
    reducer.catalog_options = dict(reducer.options)
    for instrument in instruments:
        time_minutes = (instrument.expiration_timestamp_ms - 1_000_000) / 60_000
        total_volatility = 0.5 * math.sqrt(time_minutes / (365 * 24 * 60))
        bid = black_price(
            100,
            float(instrument.strike),
            total_volatility,
            instrument.option_type,
        )
        reducer.option_books[instrument.instrument_name] = make_book(
            instrument.instrument_name,
            str(bid),
        )
        reducer.tickers[instrument.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            1_000_000,
            signed_delta=(
                Decimal("0.50") if instrument.instrument_name.endswith("ATM") else Decimal("0.40")
            ),
            mark_iv_fraction=Decimal("0.50"),
        )
        reducer.trackers[instrument.instrument_name] = EpisodeTracker(
            runtime_identity=reducer.runtime_identity,
            policy_identity=reducer.policy.identity,
            instrument_name=instrument.instrument_name,
        )
    reducer._causal_seq = 1
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )
    assert all(result.full_formula_evaluation for result in reducer.results.values())
    previous_score = reducer.results["PREVIOUS-ATM"].score_result
    assert previous_score is not None
    previous_term = next(
        factor for factor in previous_score.factors if factor.name is ScoreFactorName.TERM_RESIDUAL
    )

    evaluated_names: list[str] = []
    calculate = runtime_module.calculate_current_evaluation

    def capture_calculation(**kwargs: object) -> CurrentEvaluation:
        instrument = cast(OptionInstrument, kwargs["instrument"])
        evaluated_names.append(instrument.instrument_name)
        return calculate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "calculate_current_evaluation", capture_calculation)
    current_atm = reducer.tickers["CURRENT-ATM"]
    reducer.tickers["CURRENT-ATM"] = replace(
        current_atm,
        source_timestamp_ms=1_000_001,
        mark_iv_fraction=Decimal("0.70"),
    )
    reducer._causal_seq = 2
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 1_002, 2),
            CausalCause.TICKER_APPLIED,
            failure_domain=FailureScope.OPTION,
            affected_scopes=("OPTION:CURRENT-ATM",),
        ),
        affected_instruments=("CURRENT-ATM",),
        countable=True,
    )

    assert evaluated_names == ["CURRENT-ATM"]
    refreshed_score = reducer.results["PREVIOUS-ATM"].score_result
    assert refreshed_score is not None
    refreshed_term = next(
        factor for factor in refreshed_score.factors if factor.name is ScoreFactorName.TERM_RESIDUAL
    )
    assert refreshed_term.raw_inputs != previous_term.raw_inputs
    assert refreshed_term.normalized != previous_term.normalized


def test_latched_stale_generation_candidate_is_not_counted_as_timestamp_regression(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=1_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC-27SEP24-100010-C"
    establish_joint_witness(
        reducer,
        make_option(name, 1_000_000 + 60 * 60_000),
    )
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel, generation=5)
    reducer._ticker_generations[name] = 5
    accepted = reducer.tickers[name]

    reducer.advance_time(2_001)
    latch = reducer._ticker_currentness_latches[name]
    reducer._channels[channel].generation = latch.generation
    assert reducer.clock is not None
    candidate_timestamp = reducer.clock.interval_at(2_002).upper_ms
    assert candidate_timestamp > accepted.source_timestamp_ms

    assert reducer._apply_ticker(
        name,
        {
            "instrument_name": name,
            "timestamp": candidate_timestamp,
            "underlying_price": 101,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 1, 2_002, reducer.causal_seq),
    )

    assert reducer.tickers[name] is accepted


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
    name = "BTC-27SEP24-100010-C"
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
        commit=fact_commit(
            FactBoundary(1, 0, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer._global_continuity_epoch == 1
    episode_id = reducer.trackers[name].episode_id
    assert episode_id is not None
    reducer.atomic_states[episode_id] = PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE

    assert reducer.advance_time(1_999) == ()
    assert reducer.trackers[name].episode_id == episode_id
    commands = reducer.advance_time(2_000)

    assert reducer.results[name].reason == "TICKER_SOURCE_STALE"
    assert reducer.trackers[name].episode_id is None
    assert reducer.trackers[name].detector_state is DetectorState.UNKNOWN
    assert reducer._coverage._current_state is CoverageState.UNKNOWN
    assert reducer._global_continuity_epoch == 1
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1
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
        commit=fact_commit(
            FactBoundary(1, 0, 2_000, reducer.causal_seq),
            CausalCause.CLOCK_FACT,
        ),
        affected_instruments=(name,),
        countable=False,
    )
    assert reducer.results[name].reason == "TICKER_SOURCE_STALE"
    assert not tuple(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
        and request.request_id != unsubscribe.request_id
    )

    complete_rpc_send(reducer, unsubscribe, ingress_seq=1)
    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": unsubscribe.request_id,
                "result": unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )
    subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    complete_rpc_send(reducer, subscribe, ingress_seq=2)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "result": subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=2_003,
        ),
        processed_monotonic_ms=2_003,
    )

    assert reducer.results[name].known_evaluation
    assert reducer.results[name].reason is None
    assert not reducer.results[name].observation_eligible
    assert reducer.trackers[name].state.name == "ARMED"
    assert reducer.trackers[name].episode_id is None
    assert not reducer.event_sink.anomalies
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1
    assert reducer._global_continuity_epoch == 1

    summary = reducer.clean_stop(2_100)
    coverage_segments = cast(list[dict[str, object]], summary["coverage_segments"])
    stale_coverage = next(
        segment
        for segment in coverage_segments
        if segment["blocking_reason"] == "TICKER_SOURCE_STALE"
    )
    assert stale_coverage["state"] == "UNKNOWN"
    assert stale_coverage["affected_scopes"] == [f"OPTION:{name}"]
    assert stale_coverage["global_continuity_epoch"] == 1


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
    name = "BTC-27SEP24-100010-C"
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
        commit=fact_commit(
            FactBoundary(1, 0, 1_000, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.trackers[name].episode_id is not None
    assert len(reducer.event_sink.anomalies) == 1

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
                "bids": [["delete", "0.01", "0"], ["new", "0.02", "0.1"]],
                "asks": [
                    ["delete", "0.01000002", "0"],
                    ["new", "0.02000002", "0.1"],
                ],
            },
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )
    assert reducer.results[name].reason == "TICKER_SOURCE_STALE"

    complete_rpc_send(reducer, unsubscribe, ingress_seq=2)
    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": unsubscribe.request_id,
                "result": unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=2_002,
        ),
        processed_monotonic_ms=2_002,
    )
    subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    complete_rpc_send(reducer, subscribe, ingress_seq=3)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "result": subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=2_004,
        ),
        processed_monotonic_ms=2_004,
    )

    assert reducer.results[name].known_evaluation
    assert reducer.results[name].reason is None
    assert not reducer.results[name].observation_eligible
    assert reducer.trackers[name].state.name == "ARMED"
    assert reducer.trackers[name].episode_id is None
    assert not reducer.event_sink.anomalies
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1


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
    name = "BTC-27SEP24-100010-C"
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
        commit=fact_commit(
            FactBoundary(1, 0, 1_000, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer.trackers[name].episode_id is not None

    commands = reducer.advance_time(2_000)
    first_unsubscribe = next(
        command for command in commands if command.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    complete_rpc_send(reducer, first_unsubscribe, ingress_seq=1)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": first_unsubscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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
    complete_rpc_send(reducer, retry_unsubscribe, ingress_seq=2)
    subscribe_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": retry_unsubscribe.request_id,
                "result": retry_unsubscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=3_002,
        ),
        processed_monotonic_ms=3_002,
    )
    subscribe = next(
        command
        for command in subscribe_commands
        if command.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )
    complete_rpc_send(reducer, subscribe, ingress_seq=3)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "result": subscribe.params["channels"],
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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
            ingress_seq=reducer._last_ingress_seq + 1,
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
    name = "BTC-27SEP24-100010-C"
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
        commit=fact_commit(
            FactBoundary(1, 0, 1_000, 1),
            CausalCause.INDEX_TICK,
        ),
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

    complete_rpc_send(reducer, subscribe, ingress_seq=1)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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
    name = "BTC-27SEP24-100010-C"
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

    complete_rpc_send(reducer, subscribe, ingress_seq=1)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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


def test_ahead_and_malformed_ticker_candidates_do_not_overwrite_or_resync(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=300_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)
    name = instrument.instrument_name
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel, generation=4)
    reducer._ticker_generations[name] = 4
    accepted = reducer.tickers[name]
    result = reducer.results[name]
    episode_id = reducer.trackers[name].episode_id
    assert episode_id is not None

    assert (
        reducer.reduce(
            subscription_frame(
                channel,
                {
                    "instrument_name": name,
                    "timestamp": accepted.source_timestamp_ms + 1_000_000,
                    "underlying_price": 999,
                    "underlying_index": "index_price",
                },
                ingress_seq=1,
                received_monotonic_ms=1_002,
            ),
            processed_monotonic_ms=1_002,
        )
        == ()
    )
    assert (
        reducer.reduce(
            subscription_frame(
                channel,
                {
                    "instrument_name": name,
                    "timestamp": accepted.source_timestamp_ms + 1,
                    "underlying_index": "index_price",
                },
                ingress_seq=2,
                received_monotonic_ms=1_003,
            ),
            processed_monotonic_ms=1_003,
        )
        == ()
    )

    assert reducer.tickers[name] is accepted
    assert reducer.results[name].detector_state is result.detector_state
    assert reducer.results[name].known_evaluation == result.known_evaluation
    assert reducer.results[name].full_formula_evaluation == result.full_formula_evaluation
    assert reducer.trackers[name].episode_id == episode_id
    assert name not in reducer._ticker_currentness_latches
    assert not reducer._channels[channel].resync_requested


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
            "bids": [["new", "999", "0.1"]],
            "asks": [],
        },
        FactBoundary(1, 1, 1_001, 2),
    )
    assert reducer.option_books["SHORT"].reason == "CHANGE_ID_GAP"
    assert reducer.channel_state(channel) is ChannelState.UNSUBSCRIBE_PENDING
    unsubscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS
    )
    complete_rpc_send(reducer, unsubscribe, ingress_seq=1)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": unsubscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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
    assert not reducer.event_sink.anomalies


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
    seed_flat_available_index(reducer)
    configure_full_formula_scope(reducer, short)
    reducer.options["LONG"] = long
    reducer.catalog_options = dict(reducer.options)
    episode_id = activate_directly(reducer, short)
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
    assert not reducer.event_sink.atomics


def test_index_publication_pending_preserves_episode_layer_two_and_known_coverage(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1, ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)
    episode_id = reducer.trackers[instrument.instrument_name].episode_id
    assert episode_id is not None
    reducer.combo_catalog.complete = True
    reducer.combo_catalog.source_complete = True
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_002, 2),
            CausalCause.COMBO_CATALOG,
            failure_domain=FailureScope.COMBO_LAYER,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )
    assert reducer.atomic_states[episode_id] is PublicAtomicQuoteState.NO_ACTIVE_COMBO
    reducer.clock = TrustedClock.from_response(
        1_019_999,
        1_500,
        1_500,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )

    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 1_500, 2),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )

    assert reducer.trackers[instrument.instrument_name].episode_id == episode_id
    assert reducer.trackers[instrument.instrument_name].state.name == "ACTIVE"
    assert reducer.atomic_states[episode_id] is PublicAtomicQuoteState.NO_ACTIVE_COMBO
    assert reducer.results[instrument.instrument_name].known_evaluation
    assert reducer.results[instrument.instrument_name].reason is None
    assert reducer._coverage._current_state is CoverageState.KNOWN_COMPLETE
    assert reducer.index.publication_phase.value == "TIME_BOUNDARY_PENDING"


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
    seed_flat_available_index(reducer)
    configure_full_formula_scope(reducer, short)
    reducer.options["LONG"] = long
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

    complete_rpc_send(reducer, subscribe, ingress_seq=1)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
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
        "BTC-27SEP24-100010-C",
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
        "deribit_price_index.btc_usd",
    }


def test_combo_lifecycle_immediately_invalidates_old_layer_two_negative(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    seed_flat_available_index(reducer)
    configure_full_formula_scope(reducer, instrument)
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

    commit = fact_commit(
        FactBoundary(1, 0, 1_000, 1),
        CausalCause.COMBO_CATALOG,
        failure_domain=FailureScope.COMBO_LAYER,
    )
    short_snapshot = reducer._freeze_atomic_scope_snapshot(
        reducer.trackers["SHORT"],
        commit=commit,
    )
    unrelated_snapshot = reducer._freeze_atomic_scope_snapshot(
        reducer.trackers["UNRELATED"],
        commit=commit,
    )
    assert short_snapshot is not None
    assert unrelated_snapshot is not None
    reducer._evaluate_atomic(short_snapshot)
    reducer._evaluate_atomic(unrelated_snapshot)

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
    reducer.option_books["SECOND"] = make_book("SECOND", "1")
    reducer.tickers = {
        "FIRST": TickerState(Decimal(100), "index_price", 1_000_001),
        "SECOND": TickerState(Decimal(100), "index_price", 1_000_001),
    }
    first_episode = activate_directly(reducer, first)
    second_episode = activate_directly(reducer, second)
    assert reducer.clock is not None
    trusted = reducer.clock.interval_at(1_001)
    reducer._last_time_currentness_by_instrument = reducer._time_currentness_by_instrument(trusted)
    reducer._last_time_currentness_token = reducer._time_currentness_token(trusted)
    reducer._plan_channel_change(
        ("book.FIRST.agg2",),
        subscribe=True,
        origin_boundary=FactBoundary(1, 0, 1_000, 1),
        failure_scope=FailureScope.OPTION,
    )
    subscribe = next(
        request
        for request in reducer.pending_rpcs.values()
        if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    )

    complete_rpc_send(reducer, subscribe, ingress_seq=1)
    reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": subscribe.request_id,
                "error": {"code": 10_028, "message": "too_many_requests"},
            },
            session_epoch=1,
            ingress_seq=reducer._last_ingress_seq + 1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )

    assert reducer.trackers["FIRST"].episode_id is None
    assert reducer.trackers["FIRST"].detector_state is DetectorState.UNKNOWN
    assert reducer.trackers["SECOND"].episode_id == second_episode
    assert reducer.trackers["SECOND"].detector_state is DetectorState.ANOMALY_ACTIVE
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1
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

    reducer._update_coverage(
        commit=fact_commit(
            FactBoundary(1, 0, 1_000, 1),
            CausalCause.TIME_BOUNDARY,
        )
    )
    reducer._update_coverage(
        commit=fact_commit(
            FactBoundary(1, 0, 1_500, 2),
            CausalCause.TIME_BOUNDARY,
        )
    )
    reducer.trackers["SHORT"].resume_after_band_boundary()
    reducer._update_coverage(
        commit=fact_commit(
            FactBoundary(1, 0, 2_000, 3),
            CausalCause.TIME_BOUNDARY,
        )
    )

    assert reducer._band_suspended_duration_ms == 1_000


def test_noncountable_known_current_advances_active_duration_without_persistence(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_available_index(reducer)
    instrument = make_option("BTC-27SEP24-100010-C", 1_000_000 + 60 * 60_000)
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
        commit=fact_commit(
            FactBoundary(1, 1, 1_500, 2),
            CausalCause.OPTION_BOOK_CHANGED,
            failure_domain=FailureScope.OPTION,
            affected_scopes=(f"OPTION:{instrument.instrument_name}",),
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )
    assert reducer.results[instrument.instrument_name].known_evaluation
    assert not reducer.results[instrument.instrument_name].observation_eligible
    assert reducer.trackers[instrument.instrument_name].episode_id == episode_id

    assert not reducer._apply_index(
        {"timestamp": 500_000, "price": 100, "index_name": "btc_usd"},
        FactBoundary(1, 2, 2_000, 3),
    )

    assert reducer._known_active_duration_ms[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 500


def test_index_publication_pending_remains_known_active_duration(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1, ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)
    episode_id = reducer.trackers[instrument.instrument_name].episode_id
    assert episode_id is not None
    reducer._episode_started_ms[episode_id] = 1_000
    reducer._episode_last_trusted_ms[episode_id] = 1_000
    reducer._episode_option_type[episode_id] = OptionType.CALL
    reducer.clock = TrustedClock.from_response(
        1_019_999,
        1_500,
        1_500,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )

    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_500, 2),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )
    assert reducer.index.publication_phase.value == "TIME_BOUNDARY_PENDING"
    assert reducer.trackers[instrument.instrument_name].state.name == "ACTIVE"
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 2_000, 3),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )

    transition = reducer.trackers[instrument.instrument_name].stop(causal_seq=4)
    reducer._record_episode_end(transition.ended_episode, 2_500)

    assert reducer._known_active_duration_ms[EpisodeEndReason.CENSORED_AT_STOP.value] == 1_500


def test_causal_commit_is_explicit_frozen_and_whitelisted() -> None:
    boundary = FactBoundary(1, 7, 1_007, 11)
    commit = CausalCommit(
        boundary=boundary,
        cause=CausalCause.TICKER_APPLIED,
        failure_domain=FailureScope.OPTION,
        affected_scopes=("OPTION:SHORT",),
    )

    assert commit.boundary is boundary
    assert commit.cause is CausalCause.TICKER_APPLIED
    assert commit.failure_domain is FailureScope.OPTION
    assert commit.affected_scopes == ("OPTION:SHORT",)
    with pytest.raises(FrozenInstanceError):
        commit.affected_scopes = ("GLOBAL",)  # type: ignore[misc]
    with pytest.raises((TypeError, ValueError), match="cause"):
        CausalCommit(
            boundary=boundary,
            cause=cast(CausalCause, "RESULT_INFERRED"),
            failure_domain=FailureScope.OPTION,
            affected_scopes=("OPTION:SHORT",),
        )
    with pytest.raises((TypeError, ValueError), match="failure"):
        CausalCommit(
            boundary=boundary,
            cause=CausalCause.TICKER_APPLIED,
            failure_domain=cast(FailureScope, "UNKNOWN_DOMAIN"),
            affected_scopes=("OPTION:SHORT",),
        )
    with pytest.raises(TypeError):
        runtime_module.CoverageTracker(0)  # type: ignore[call-arg]


def test_one_continuity_incident_restarts_once_then_recovery_allows_one_new_restart(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    clock_commit = CausalCommit(
        boundary=FactBoundary(1, 1, 1_001, 1),
        cause=CausalCause.CLOCK_GAP,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )
    incident = reducer._restart_global_continuity(clock_commit)
    derived_index_commit = CausalCommit(
        boundary=FactBoundary(1, 1, 1_001, 1),
        cause=CausalCause.INDEX_CONTINUITY_GAP,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )
    assert (
        reducer._restart_global_continuity(
            derived_index_commit,
            incident=incident,
        )
        is incident
    )
    assert reducer._global_continuity_epoch == 2

    reducer._recover_continuity_incident(
        incident,
        boundary=FactBoundary(1, 2, 1_002, 2),
    )
    later_commit = CausalCommit(
        boundary=FactBoundary(1, 2, 2_001, 2),
        cause=CausalCause.INDEX_CONTINUITY_GAP,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )
    later_incident = reducer._restart_global_continuity(later_commit)

    assert later_incident != incident
    assert reducer._global_continuity_epoch == 3


def test_clock_incident_stays_open_through_clock_rebootstrap_until_index_recovery(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    clock_gap = FactBoundary(1, 1, 1_001, 1)
    reducer._invalidate_clock_index(clock_gap, reason=CausalCause.CLOCK_GAP.value)
    incident = reducer._active_continuity_incident
    assert incident is not None
    assert reducer._global_continuity_epoch == 2

    reducer.clock = TrustedClock.from_response(
        1_000_000,
        1_002,
        1_002,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.settle_fact(
        commit=CausalCommit(
            boundary=FactBoundary(1, 2, 1_002, 2),
            cause=CausalCause.CLOCK_FACT,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        ),
        affected_instruments=(),
        countable=False,
    )
    assert reducer._active_continuity_incident is incident

    assert not reducer._apply_index(
        {"timestamp": "invalid", "price": 100, "index_name": "btc_usd"},
        FactBoundary(1, 3, 1_003, 3),
    )
    assert reducer._active_continuity_incident is incident
    assert reducer._global_continuity_epoch == 2


@pytest.mark.parametrize("trigger", ("market_fact", "time_advance", "clean_stop"))
def test_source_currentness_settles_before_detector_on_every_boundary(
    trigger: str,
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=1_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    configure_full_formula_scope(
        reducer,
        instrument,
        ticker_source_timestamp_ms=1_000_000,
    )
    reducer.clock = TrustedClock.from_response(
        1_001_001,
        2_000,
        2_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    seen_settled_states: list[str] = []
    calculate = runtime_module.calculate_current_evaluation

    def require_settled_currentness(
        *,
        policy: RadarPolicy,
        instrument: OptionInstrument,
        trusted_time: TimeInterval,
        causal_seq: int,
        option_book: ContinuousOrderBook | None,
        ticker: TickerState | None,
        causal_closes: tuple[Decimal, ...] | None,
        baseline_statistics: BaselineStatistics | None = None,
        baseline_unavailable_reason: str = "INDEX_BASELINE_WARMUP",
        ticker_unavailable_reason: str = "FORWARD_TICKER_UNKNOWN",
        ticker_continuity_gap: bool = False,
    ) -> CurrentEvaluation:
        settled = reducer._settled_ticker_currentness[instrument.instrument_name]
        seen_settled_states.append(settled.state.value)
        return calculate(
            policy=policy,
            instrument=instrument,
            trusted_time=trusted_time,
            causal_seq=causal_seq,
            option_book=option_book,
            ticker=ticker,
            causal_closes=causal_closes,
            baseline_statistics=baseline_statistics,
            baseline_unavailable_reason=baseline_unavailable_reason,
            ticker_unavailable_reason=ticker_unavailable_reason,
            ticker_continuity_gap=ticker_continuity_gap,
        )

    monkeypatch.setattr(
        runtime_module,
        "calculate_current_evaluation",
        require_settled_currentness,
    )
    if trigger == "market_fact":
        assert reducer._apply_book(
            instrument.instrument_name,
            {
                "type": "change",
                "timestamp": 2,
                "instrument_name": instrument.instrument_name,
                "change_id": 2,
                "prev_change_id": 1,
                "bids": [],
                "asks": [],
            },
            FactBoundary(1, 1, 2_001, 1),
        )
    elif trigger == "time_advance":
        reducer.advance_time(2_001)
    else:
        reducer.clean_stop(2_001)

    assert seen_settled_states
    assert seen_settled_states[0] == "SOURCE_STALE"
    assert reducer.results[instrument.instrument_name].reason == "TICKER_SOURCE_STALE"


def test_settle_source_currentness_is_network_free(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=1_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    configure_full_formula_scope(
        reducer,
        instrument,
        ticker_source_timestamp_ms=1_000_000,
    )
    acknowledge_channel(reducer, ticker_channel(instrument.instrument_name))
    reducer.clock = TrustedClock.from_response(
        1_001_001,
        2_000,
        2_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    pending_before = tuple(reducer.pending_rpcs)

    newly_stale = reducer.settle_source_currentness(FactBoundary(1, 1, 2_001, 1))

    assert newly_stale == (instrument.instrument_name,)
    assert tuple(reducer.pending_rpcs) == pending_before


def test_market_boundary_settles_ttl_crossing_in_an_unrelated_full_scope(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=1_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    first = make_option("FIRST", 1_000_000 + 60 * 60_000)
    second = make_option("SECOND", first.expiration_timestamp_ms + 60_000)
    configure_full_formula_scope(reducer, first)
    reducer.options[second.instrument_name] = second
    reducer.catalog_options[second.instrument_name] = second
    reducer.trackers[second.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=second.instrument_name,
    )
    reducer.option_books[second.instrument_name] = make_book(second.instrument_name, "1")
    reducer.tickers[second.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_000,
    )
    reducer.settle_fact(
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 1_001, 1),
            cause=CausalCause.TIME_BOUNDARY,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )
    assert reducer.results[second.instrument_name].reason != "TICKER_SOURCE_STALE"

    reducer.clock = TrustedClock.from_response(
        1_001_001,
        2_000,
        2_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    old_bid = reducer.option_books[first.instrument_name].levels("bid")[0].price
    old_ask = reducer.option_books[first.instrument_name].levels("ask")[0].price
    assert reducer._apply_book(
        first.instrument_name,
        {
            "type": "change",
            "timestamp": 2,
            "instrument_name": first.instrument_name,
            "change_id": 2,
            "prev_change_id": 1,
            "bids": [["delete", str(old_bid), "0"], ["new", "999", "0.1"]],
            "asks": [["delete", str(old_ask), "0"], ["new", "1000", "0.1"]],
        },
        FactBoundary(1, 2, 2_001, 2),
    )

    assert reducer._settled_ticker_currentness[second.instrument_name].state.value == "SOURCE_STALE"
    assert reducer.results[second.instrument_name].reason == "TICKER_SOURCE_STALE"
    assert reducer._coverage._current_trigger_cause == "OPTION_BOOK_CHANGED"
    assert reducer._coverage._current_blocking_reason == "TICKER_SOURCE_STALE"
    assert reducer._coverage._current_affected_scopes == (
        "OPTION:FIRST",
        "OPTION:SECOND",
    )


def test_local_book_fact_recalculates_only_changed_member_and_refreshes_scope_truth(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("FIRST", expiry)
    second = make_option("SECOND", expiry)
    other_scope = make_option("OTHER", expiry + 60_000)
    configure_full_formula_scope(reducer, first)
    for instrument in (second, other_scope):
        reducer.options[instrument.instrument_name] = instrument
        reducer.catalog_options[instrument.instrument_name] = instrument
        reducer.trackers[instrument.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=instrument.instrument_name,
        )
        reducer.option_books[instrument.instrument_name] = make_book(
            instrument.instrument_name,
            None,
        )
        reducer.tickers[instrument.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            1_000_000,
        )
    reducer.settle_fact(
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 1_001, 1),
            cause=CausalCause.TIME_BOUNDARY,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )
    captured: list[ScopeSnapshot] = []
    scope_truths: list[object] = []
    current_scope_truth = reducer._current_scope_truth
    evaluated_names: list[str] = []
    calculate = runtime_module.calculate_current_evaluation

    def capture_snapshot(snapshot: ScopeSnapshot) -> object:
        captured.append(snapshot)
        value = current_scope_truth(snapshot)
        scope_truths.append(value)
        return value

    def capture_calculation(**kwargs: object) -> CurrentEvaluation:
        instrument = cast(OptionInstrument, kwargs["instrument"])
        evaluated_names.append(instrument.instrument_name)
        return calculate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reducer, "_current_scope_truth", capture_snapshot)
    monkeypatch.setattr(runtime_module, "calculate_current_evaluation", capture_calculation)
    reducer.settle_fact(
        commit=CausalCommit(
            boundary=FactBoundary(1, 2, 1_002, 2),
            cause=CausalCause.OPTION_BOOK_CHANGED,
            failure_domain=FailureScope.OPTION,
            affected_scopes=("OPTION:FIRST",),
        ),
        affected_instruments=(first.instrument_name,),
        countable=True,
    )

    assert len(captured) == 1
    snapshot = captured[0]
    assert isinstance(snapshot, runtime_module.ScopeSnapshot)
    assert snapshot.commit.cause is CausalCause.OPTION_BOOK_CHANGED
    assert snapshot.commit.affected_scopes == ("OPTION:FIRST",)
    assert tuple(item.instrument.instrument_name for item in snapshot.current) == ("FIRST",)
    assert evaluated_names == ["FIRST"]
    assert all(item.result is not None for item in snapshot.current)
    assert tuple(item.instrument_name for item, _result in snapshot.scope_results) == (
        "FIRST",
        "SECOND",
    )
    assert len(scope_truths) == 1
    assert scope_truths[0].aggregate.instrument_count == 2  # type: ignore[attr-defined]

    before = current_scope_truth(snapshot)
    reducer.options.clear()
    reducer.trackers.clear()
    reducer.results.clear()
    assert current_scope_truth(snapshot) == before


def test_high_fanout_local_fact_shares_one_history_tail_and_one_formula_call(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    instruments = tuple(
        make_option(f"BTC-08AUG26-{100_000 + index}-C", expiry) for index in range(320)
    )
    reducer.options = {item.instrument_name: item for item in instruments}
    reducer.catalog_options = dict(reducer.options)
    for instrument in instruments:
        reducer.trackers[instrument.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=instrument.instrument_name,
        )
        reducer.option_books[instrument.instrument_name] = make_book(
            instrument.instrument_name,
            None,
        )
        reducer.tickers[instrument.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            1_000_000,
        )
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )

    tail_calls = 0
    calculation_calls = 0
    score_context_members: list[tuple[str, ...]] = []
    current_tail = reducer.index_history.current_tail
    calculate = runtime_module.calculate_current_evaluation
    build_score_contexts = cast(Any, build_score_feature_contexts)

    def count_tail(*args: object, **kwargs: object) -> IndexHistoryState:
        nonlocal tail_calls
        tail_calls += 1
        return current_tail(*args, **kwargs)  # type: ignore[arg-type]

    def count_calculation(**kwargs: object) -> CurrentEvaluation:
        nonlocal calculation_calls
        calculation_calls += 1
        return calculate(**kwargs)  # type: ignore[arg-type]

    def capture_score_context_members(**kwargs: object) -> object:
        selected = kwargs.get("instrument_names")
        score_context_members.append(
            tuple(selected)  # type: ignore[arg-type]
            if selected is not None
            else tuple(cast(dict[str, object], kwargs["options"]))
        )
        return build_score_contexts(**kwargs)

    monkeypatch.setattr(reducer.index_history, "current_tail", count_tail)
    monkeypatch.setattr(runtime_module, "calculate_current_evaluation", count_calculation)
    monkeypatch.setattr(
        runtime_module,
        "build_score_feature_contexts",
        capture_score_context_members,
    )
    known_before = sum(
        scope.known_per_instrument_detector_evaluation_count
        for scope in reducer._scope_counts.values()
    )
    changed = instruments[0]
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 1_002, 2),
            CausalCause.OPTION_BOOK_CHANGED,
            failure_domain=FailureScope.OPTION,
            affected_scopes=(f"OPTION:{changed.instrument_name}",),
        ),
        affected_instruments=(changed.instrument_name,),
        countable=True,
    )

    assert calculation_calls == 1
    assert tail_calls == 1
    assert score_context_members == [(changed.instrument_name,)]
    assert (
        sum(
            scope.known_per_instrument_detector_evaluation_count
            for scope in reducer._scope_counts.values()
        )
        == known_before + 1
    )


def test_full_scope_reuses_one_baseline_statistics_for_128_instruments(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    instruments = tuple(make_option(f"OPTION-{index:03d}", expiry) for index in range(128))
    total_volatility = 0.5 * math.sqrt(60 / (365 * 24 * 60))
    bid = Decimal(
        str(
            black_price(
                100,
                float(instruments[0].strike),
                total_volatility,
                instruments[0].option_type,
            )
        )
    )
    reducer.options = {item.instrument_name: item for item in instruments}
    reducer.catalog_options = dict(reducer.options)
    for instrument in instruments:
        reducer.trackers[instrument.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=instrument.instrument_name,
        )
        reducer.option_books[instrument.instrument_name] = make_book(
            instrument.instrument_name,
            str(bid),
        )
        reducer.tickers[instrument.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            1_000_000,
        )

    statistics_calls = 0
    compute_statistics = baseline_module.compute_baseline_statistics

    def count_statistics(**kwargs: object) -> BaselineStatistics:
        nonlocal statistics_calls
        statistics_calls += 1
        return compute_statistics(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "compute_baseline_statistics", count_statistics)
    reducer.settle_fact(
        commit=fact_commit(FactBoundary(1, 1, 1_001, 1), CausalCause.TIME_BOUNDARY),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )

    assert statistics_calls == 1
    assert all(result.full_formula_evaluation for result in reducer.results.values())
    assert len(reducer._baseline_statistics_by_spec) == 1

    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 1_002, 2),
            CausalCause.OPTION_BOOK_CHANGED,
            failure_domain=FailureScope.OPTION,
            affected_scopes=(f"OPTION:{instruments[0].instrument_name}",),
        ),
        affected_instruments=(instruments[0].instrument_name,),
        countable=False,
    )

    assert statistics_calls == 1


def test_baseline_statistics_cache_replaces_tail_and_is_bounded_by_policy_specs(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    assert reducer.clock is not None
    trusted = reducer.clock.interval_at(1_000)
    tail = reducer.index_history.current_tail(
        reducer.policy.largest_lookback_minutes,
        trusted_time=trusted,
        source_stale_deadline_ms=(
            reducer.policy.runtime_limits.index_history_source_stale_deadline_ms
        ),
    )
    statistics_calls = 0
    compute_statistics = baseline_module.compute_baseline_statistics

    def count_statistics(**kwargs: object) -> BaselineStatistics:
        nonlocal statistics_calls
        statistics_calls += 1
        return compute_statistics(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "compute_baseline_statistics", count_statistics)
    first_band, second_band = reducer.policy.tte_bands

    for _ in range(128):
        reducer._baseline_statistics_for(band=first_band, tail=tail)
    assert statistics_calls == 1

    for index in range(1, 51):
        changed_tail = replace(
            tail,
            points=(
                *tail.points[:-1],
                replace(tail.points[-1], average_price=Decimal(100 + index)),
            ),
        )
        reducer._baseline_statistics_for(band=first_band, tail=changed_tail)
        reducer._baseline_statistics_for(band=second_band, tail=changed_tail)

    assert statistics_calls == 101
    assert len(reducer._baseline_statistics_by_spec) == 2

    reducer.begin_session(session_epoch=2, monotonic_ms=2_000)
    assert reducer._baseline_statistics_by_spec == {}


def test_option_lifecycle_unknown_recomputes_aggregate_from_one_full_scope_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("BTC-08AUG26-100000-C", expiry)
    second = make_option("BTC-08AUG26-101000-C", expiry)
    configure_full_formula_scope(reducer, first)
    reducer.options[second.instrument_name] = second
    reducer.catalog_options[second.instrument_name] = second
    reducer.trackers[second.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=second.instrument_name,
    )
    reducer.option_books[second.instrument_name] = make_book(second.instrument_name, "1")
    reducer.tickers[second.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_000,
    )
    reducer.settle_fact(
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 1_001, 1),
            cause=CausalCause.TIME_BOUNDARY,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )
    captured: list[ScopeSnapshot] = []
    current_scope_truth = reducer._current_scope_truth

    def capture_snapshot(snapshot: ScopeSnapshot) -> object:
        captured.append(snapshot)
        return current_scope_truth(snapshot)

    monkeypatch.setattr(reducer, "_current_scope_truth", capture_snapshot)
    reducer._apply_option_lifecycle(
        {"instrument_name": first.instrument_name, "state": "halted"},
        FactBoundary(1, 2, 1_002, 2),
    )

    assert len(captured) == 1
    assert tuple(item.instrument.instrument_name for item in captured[0].current) == (
        "BTC-08AUG26-100000-C",
        "BTC-08AUG26-101000-C",
    )
    assert reducer.results[first.instrument_name].reason == "OPTION_LIFECYCLE_HALTED"
    aggregate = next(iter(reducer.aggregate_results.values()))
    assert aggregate.coverage is DetectorCoverage.UNKNOWN


def test_final_btc_lifecycle_reuses_unaffected_immutable_current_results(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    target = make_option("BTC-08AUG26-100000-C", expiry)
    peer = make_option("BTC-08AUG26-101000-C", expiry)
    other_expiry = make_option("BTC-09AUG26-100000-C", expiry + 60 * 60_000)
    other_type = OptionInstrument(
        "BTC-08AUG26-100000-P",
        expiry,
        Decimal("100"),
        OptionType.PUT,
        target.amount,
    )
    instruments = (target, peer, other_expiry, other_type)
    reducer.options = {item.instrument_name: item for item in instruments}
    reducer.catalog_options = dict(reducer.options)
    for item in instruments:
        reducer.trackers[item.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=item.instrument_name,
        )
        reducer.option_books[item.instrument_name] = make_book(item.instrument_name, None)
        reducer.tickers[item.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            1_000_000,
        )
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )
    unaffected_before = {
        item.instrument_name: reducer.results[item.instrument_name]
        for item in (other_expiry, other_type)
    }
    evaluated_names: list[str] = []
    calculate = runtime_module.calculate_current_evaluation

    def capture_calculation(**kwargs: object) -> CurrentEvaluation:
        instrument = cast(OptionInstrument, kwargs["instrument"])
        evaluated_names.append(instrument.instrument_name)
        return calculate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "calculate_current_evaluation", capture_calculation)

    reducer._apply_option_lifecycle(
        {"instrument_name": target.instrument_name, "state": "inactive"},
        FactBoundary(1, 2, 1_002, 2),
    )

    assert set(evaluated_names) == {peer.instrument_name}
    assert target.instrument_name not in reducer.options
    for name, result in unaffected_before.items():
        assert reducer.results[name] is result


def test_deribit_0800_expiry_burst_never_recomputes_other_scopes(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry_0800_ms = 8 * 60 * 60_000
    expiring_calls = tuple(
        make_option(
            f"BTC-08AUG26-{100_000 + index}-C",
            expiry_0800_ms,
        )
        for index in range(32)
    )
    protected_puts = tuple(
        OptionInstrument(
            f"BTC-08AUG26-{100_000 + index}-P",
            expiry_0800_ms,
            Decimal(100_000 + index),
            OptionType.PUT,
            expiring_calls[0].amount,
        )
        for index in range(16)
    )
    protected_next_expiry = tuple(
        make_option(
            f"BTC-09AUG26-{100_000 + index}-C",
            expiry_0800_ms + 60 * 60_000,
        )
        for index in range(16)
    )
    instruments = (*expiring_calls, *protected_puts, *protected_next_expiry)
    reducer.options = {item.instrument_name: item for item in instruments}
    reducer.catalog_options = dict(reducer.options)
    for item in instruments:
        reducer.trackers[item.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=item.instrument_name,
        )
        reducer.option_books[item.instrument_name] = make_book(item.instrument_name, None)
        reducer.tickers[item.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            1_000_000,
        )
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )
    protected = (*protected_puts, *protected_next_expiry)
    protected_results = {
        item.instrument_name: reducer.results[item.instrument_name] for item in protected
    }
    evaluated_names: list[str] = []
    calculate = runtime_module.calculate_current_evaluation

    def capture_calculation(**kwargs: object) -> CurrentEvaluation:
        instrument = cast(OptionInstrument, kwargs["instrument"])
        evaluated_names.append(instrument.instrument_name)
        return calculate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "calculate_current_evaluation", capture_calculation)

    for causal_seq, instrument in enumerate(expiring_calls, start=2):
        reducer._apply_option_lifecycle(
            {"instrument_name": instrument.instrument_name, "state": "inactive"},
            FactBoundary(1, causal_seq, 1_000 + causal_seq, causal_seq),
        )

    protected_names = set(protected_results)
    assert not protected_names.intersection(evaluated_names)
    assert not set(expiring.instrument_name for expiring in expiring_calls).intersection(
        reducer.options
    )
    for name, result in protected_results.items():
        assert reducer.results[name] is result
    assert not any(
        key[:2] == (expiry_0800_ms, OptionType.CALL) for key in reducer.aggregate_results
    )


def test_late_ticker_after_ttl_settles_the_accepted_ticker_to_unknown(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=1_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC-27SEP24-100010-C"
    instrument = make_option(name, 1_000_000 + 60 * 60_000)
    establish_joint_witness(reducer, instrument)
    accepted = reducer.tickers[name]
    episode_id = reducer.trackers[name].episode_id
    assert episode_id is not None
    channel = ticker_channel(name)
    acknowledge_channel(reducer, channel, generation=7)
    reducer._ticker_generations[name] = 7

    reducer.reduce(
        subscription_frame(
            channel,
            {
                "instrument_name": name,
                "timestamp": accepted.source_timestamp_ms - 1,
                "underlying_price": 99,
                "underlying_index": "index_price",
            },
            ingress_seq=1,
            received_monotonic_ms=2_001,
        ),
        processed_monotonic_ms=2_001,
    )

    assert reducer.tickers[name] is accepted
    assert reducer._settled_ticker_currentness[name].state.value == "SOURCE_STALE"
    assert reducer.results[name].reason == "TICKER_SOURCE_STALE"
    assert reducer.trackers[name].detector_state is DetectorState.UNKNOWN
    assert reducer.trackers[name].episode_id is None
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_DETECTOR.value] == 1


def test_combo_book_after_short_ticker_ttl_cannot_emit_atomic_evidence(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=1_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 60 * 60_000
    short = make_option("SHORT", expiry)
    establish_joint_witness(reducer, short)
    episode_id = reducer.trackers[short.instrument_name].episode_id
    assert episode_id is not None
    long = OptionInstrument(
        "LONG",
        expiry,
        Decimal(110),
        OptionType.CALL,
        short.amount,
    )
    reducer.options[long.instrument_name] = long
    reducer.catalog_options[long.instrument_name] = long
    reducer.trackers[long.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=long.instrument_name,
    )
    reducer.option_books[long.instrument_name] = make_book(long.instrument_name, None)
    reducer.combos["COMBO"] = ComboInstrument(
        "COMBO",
        "active",
        (ComboLeg("SHORT", Decimal("-1")), ComboLeg("LONG", Decimal("1"))),
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    reducer.combo_catalog.complete = True
    reducer.combo_catalog.source_complete = True
    reducer.combo_books["COMBO"] = ContinuousOrderBook("COMBO")

    assert reducer._apply_book(
        "COMBO",
        {
            "type": "snapshot",
            "timestamp": 2,
            "instrument_name": "COMBO",
            "change_id": 1,
            "bids": [],
            "asks": [["new", "-1", "0.1"]],
        },
        FactBoundary(1, 1, 2_001, 2),
    )

    assert reducer.results[short.instrument_name].reason == "TICKER_SOURCE_STALE"
    assert reducer.trackers[short.instrument_name].episode_id is None
    assert episode_id not in reducer.atomic_states
    assert not reducer.event_sink.atomics


def test_runtime_writer_validates_activation_then_later_atomic_combo_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation_count=1,
        ticker_source_stale_deadline_ms=300_000,
    )
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    expiry = 1_000_000 + 60 * 60_000
    short = make_option("SHORT", expiry)
    establish_joint_witness(reducer, short)
    episode_id = reducer.trackers[short.instrument_name].episode_id
    assert episode_id is not None
    long = OptionInstrument(
        "LONG",
        expiry,
        Decimal(110),
        OptionType.CALL,
        short.amount,
    )
    reducer.options[long.instrument_name] = long
    reducer.catalog_options[long.instrument_name] = long
    reducer.trackers[long.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=long.instrument_name,
    )
    reducer.option_books[long.instrument_name] = make_book(long.instrument_name, None)
    reducer.tickers[long.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_000,
    )
    reducer.combos["COMBO"] = ComboInstrument(
        "COMBO",
        "active",
        (ComboLeg("SHORT", Decimal("-1")), ComboLeg("LONG", Decimal("1"))),
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    reducer.combo_catalog.complete = True
    reducer.combo_catalog.source_complete = True
    reducer.combo_books["COMBO"] = ContinuousOrderBook("COMBO")
    reducer._causal_seq = 2

    assert reducer._apply_book(
        "COMBO",
        {
            "type": "snapshot",
            "timestamp": 2,
            "instrument_name": "COMBO",
            "change_id": 1,
            "bids": [],
            "asks": [["new", "-1", "0.1"]],
        },
        FactBoundary(1, 2, 1_100, 2),
    )
    anomaly = next(iter(reducer.event_sink.anomalies))
    atomic = next(iter(reducer.event_sink.atomics))
    assert anomaly["episode_identity"] == atomic["episode_identity"] == episode_id
    anomaly_causal_seq = anomaly["causal_seq"]
    detector_causal_seq = atomic["detector_causal_seq"]
    assert isinstance(anomaly_causal_seq, int)
    assert isinstance(detector_causal_seq, int)
    assert anomaly_causal_seq < detector_causal_seq
    assert atomic["detector_causal_seq"] == atomic["quote_causal_seq"] == 2

    reducer.clean_stop(1_200)
    assert not reducer.event_sink.anomalies
    assert not reducer.event_sink.atomics


def test_fact_transaction_preserves_trigger_and_concurrent_source_stale_attribution(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=1_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    first = make_option("FIRST", 1_000_000 + 60 * 60_000)
    second = make_option("SECOND", first.expiration_timestamp_ms + 60_000)
    configure_full_formula_scope(reducer, first)
    reducer.options[second.instrument_name] = second
    reducer.catalog_options[second.instrument_name] = second
    reducer.trackers[second.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=second.instrument_name,
    )
    reducer.option_books[second.instrument_name] = make_book(second.instrument_name, "1")
    reducer.tickers[second.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_000,
    )
    reducer.settle_fact(
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 1_001, 1),
            cause=CausalCause.TIME_BOUNDARY,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        ),
        affected_instruments=tuple(reducer.options),
        countable=False,
    )
    reducer.clock = TrustedClock.from_response(
        1_001_001,
        2_000,
        2_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    captured: list[ScopeSnapshot] = []
    current_scope_truth = reducer._current_scope_truth

    def capture_snapshot(snapshot: ScopeSnapshot) -> object:
        captured.append(snapshot)
        return current_scope_truth(snapshot)

    monkeypatch.setattr(reducer, "_current_scope_truth", capture_snapshot)
    old_bid = reducer.option_books[first.instrument_name].levels("bid")[0].price
    old_ask = reducer.option_books[first.instrument_name].levels("ask")[0].price
    assert reducer._apply_book(
        first.instrument_name,
        {
            "type": "change",
            "timestamp": 2,
            "instrument_name": first.instrument_name,
            "change_id": 2,
            "prev_change_id": 1,
            "bids": [["delete", str(old_bid), "0"], ["new", "999", "0.1"]],
            "asks": [["delete", str(old_ask), "0"], ["new", "1000", "0.1"]],
        },
        FactBoundary(1, 2, 2_001, 2),
    )

    assert captured
    for snapshot in captured:
        assert snapshot.commit.cause is CausalCause.OPTION_BOOK_CHANGED
        assert snapshot.commit.affected_scopes == ("OPTION:FIRST",)
        assert tuple(
            (effect.cause, effect.failure_domain, effect.affected_scopes)
            for effect in snapshot.commit.concurrent_effects
        ) == (
            (
                CausalCause.TICKER_SOURCE_STALE,
                FailureScope.OPTION,
                ("OPTION:FIRST", "OPTION:SECOND"),
            ),
        )
        assert snapshot.commit.transaction_affected_scopes == (
            "OPTION:FIRST",
            "OPTION:SECOND",
        )
    assert reducer.results[second.instrument_name].reason == "TICKER_SOURCE_STALE"


def test_ordered_queue_lag_blocks_observation_until_catch_up_without_epoch_restart(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)
    result = reducer.results[instrument.instrument_name]
    counter = reducer._scope_counter(
        instrument.option_type,
        result.band_id or "",
    )
    count_before = counter.known_per_instrument_detector_evaluation_count
    acknowledge_channel(reducer, book_channel(instrument.instrument_name))
    reducer._baseline_statistics_by_spec.clear()
    statistics_calls = 0
    compute_statistics = baseline_module.compute_baseline_statistics

    def count_statistics(**kwargs: object) -> BaselineStatistics:
        nonlocal statistics_calls
        statistics_calls += 1
        return compute_statistics(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "compute_baseline_statistics", count_statistics)

    delayed = subscription_frame(
        book_channel(instrument.instrument_name),
        {
            "type": "change",
            "timestamp": 2,
            "instrument_name": instrument.instrument_name,
            "change_id": 2,
            "prev_change_id": 1,
            "bids": [],
            "asks": [],
        },
        ingress_seq=1,
        received_monotonic_ms=1_100,
    )
    reducer.reduce(delayed, processed_monotonic_ms=2_101)

    current = reducer.results[instrument.instrument_name]
    assert not current.known_evaluation
    assert current.reason == "QUEUE_LAG_CURRENTNESS"
    assert not current.observation_eligible
    assert counter.known_per_instrument_detector_evaluation_count == count_before
    assert reducer._coverage._current_trigger_cause == "OPTION_BOOK_FACT"
    assert reducer._coverage._current_blocking_reason == "QUEUE_LAG_CURRENTNESS"
    assert reducer._coverage._current_affected_scopes == ("GLOBAL",)
    assert reducer._global_continuity_epoch == 1
    assert reducer.diagnostics.session_gap_count == 0
    assert statistics_calls == 0

    catch_up = InboundEnvelope(
        {
            "jsonrpc": "2.0",
            "method": "heartbeat",
            "params": {"type": "heartbeat"},
        },
        session_epoch=1,
        ingress_seq=2,
        received_monotonic_ms=2_102,
    )
    reducer.reduce(catch_up, processed_monotonic_ms=2_102)

    recovered = reducer.results[instrument.instrument_name]
    assert recovered.known_evaluation
    assert not recovered.observation_eligible
    assert counter.known_per_instrument_detector_evaluation_count == count_before
    assert reducer._coverage._current_blocking_reason == "NONE"
    assert reducer._global_continuity_epoch == 1
    assert statistics_calls == 1

    summary = reducer.clean_stop(2_200)
    coverage_segments = cast(list[dict[str, object]], summary["coverage_segments"])
    incident = next(
        segment
        for segment in coverage_segments
        if segment["blocking_reason"] == "QUEUE_LAG_CURRENTNESS"
    )
    assert incident["start_monotonic_ms"] == 1_100
    assert incident["end_monotonic_ms"] == 2_102
    assert incident["global_continuity_epoch"] == 1


def test_sustained_queue_lag_rebuilds_only_enter_and_recovery_edges(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    first = make_option(
        "BTC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    second = make_option(
        "BTC-27SEP24-100020-C",
        1_000_000 + 120 * 60_000,
    )
    reducer.options = {
        first.instrument_name: first,
        second.instrument_name: second,
    }
    reducer.catalog_options = dict(reducer.options)
    assert reducer.clock is not None
    ticker_timestamp = reducer.clock.interval_at(1_001).upper_ms
    for instrument in (first, second):
        reducer.trackers[instrument.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=instrument.instrument_name,
        )
        reducer.option_books[instrument.instrument_name] = make_book(
            instrument.instrument_name,
            "1",
        )
        reducer.tickers[instrument.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            ticker_timestamp,
        )
        acknowledge_channel(reducer, book_channel(instrument.instrument_name))
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 0, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(first.instrument_name, second.instrument_name),
        countable=True,
    )

    settled_scopes: list[tuple[str, ...]] = []
    current_scope_truth = reducer._current_scope_truth

    def capture_scope(snapshot: ScopeSnapshot) -> object:
        settled_scopes.append(tuple(item.instrument.instrument_name for item in snapshot.current))
        return current_scope_truth(snapshot)

    monkeypatch.setattr(reducer, "_current_scope_truth", capture_scope)
    reducer.reduce(
        subscription_frame(
            book_channel(first.instrument_name),
            {
                "type": "change",
                "timestamp": 2,
                "instrument_name": first.instrument_name,
                "change_id": 2,
                "prev_change_id": 1,
                "bids": [["new", "1.1", "0.1"]],
                "asks": [],
            },
            ingress_seq=1,
            received_monotonic_ms=1_100,
        ),
        processed_monotonic_ms=2_101,
    )
    assert {name for scope in settled_scopes for name in scope} == {
        first.instrument_name,
        second.instrument_name,
    }

    settled_scopes.clear()
    count_before = sum(
        scope.known_per_instrument_detector_evaluation_count
        for scope in reducer._scope_counts.values()
    )
    reducer.reduce(
        subscription_frame(
            book_channel(second.instrument_name),
            {
                "type": "change",
                "timestamp": 3,
                "instrument_name": second.instrument_name,
                "change_id": 2,
                "prev_change_id": 1,
                "bids": [["new", "1.1", "0.1"]],
                "asks": [],
            },
            ingress_seq=2,
            received_monotonic_ms=1_101,
        ),
        processed_monotonic_ms=2_102,
    )

    assert settled_scopes == [(second.instrument_name,)]
    assert all(not result.observation_eligible for result in reducer.results.values())
    assert (
        sum(
            scope.known_per_instrument_detector_evaluation_count
            for scope in reducer._scope_counts.values()
        )
        == count_before
    )


def test_coverage_preserves_heterogeneous_nonpublication_blockers(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("BTC-27SEP24-100010-C", expiry)
    second = make_option("BTC-27SEP24-100020-C", expiry)
    reducer.options = {
        first.instrument_name: first,
        second.instrument_name: second,
    }
    reducer.catalog_options = dict(reducer.options)
    assert reducer.clock is not None
    timestamp = reducer.clock.interval_at(1_001).upper_ms
    for instrument in (first, second):
        reducer.trackers[instrument.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=instrument.instrument_name,
        )
        reducer.option_books[instrument.instrument_name] = make_book(
            instrument.instrument_name,
            "1",
        )
        reducer.tickers[instrument.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            timestamp,
        )
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 0, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(first.instrument_name, second.instrument_name),
        countable=True,
    )
    first_result = reducer.results[first.instrument_name]
    second_result = reducer.results[second.instrument_name]
    reducer.results[first.instrument_name] = replace(
        first_result,
        reason="OPTION_BOOK_GAP",
        known_evaluation=False,
        full_formula_evaluation=False,
    )
    reducer.results[second.instrument_name] = replace(
        second_result,
        reason="TICKER_SOURCE_STALE",
        known_evaluation=False,
        full_formula_evaluation=False,
    )
    reducer.aggregate_results.clear()
    reducer._update_coverage(
        commit=fact_commit(
            FactBoundary(1, 0, 1_100, 2),
            CausalCause.OPTION_BOOK_FACT,
        )
    )

    assert tuple(
        (group.blocking_reason, group.affected_scopes)
        for group in reducer._coverage._current_blocking_groups
    ) == (
        ("OPTION_BOOK_UNAVAILABLE", (f"OPTION:{first.instrument_name}",)),
        ("TICKER_SOURCE_STALE", (f"OPTION:{second.instrument_name}",)),
    )
    assert reducer._coverage._current_blocking_reason == "CURRENT_SCOPE_INCOMPLETE"

    summary = reducer.clean_stop(1_300)
    coverage_segments = cast(list[dict[str, object]], summary["coverage_segments"])
    assert any(
        {
            group["blocking_reason"]
            for group in cast(list[dict[str, object]], segment["blocking_groups"])
        }
        == {"OPTION_BOOK_UNAVAILABLE", "TICKER_SOURCE_STALE"}
        for segment in coverage_segments
    )


def test_coverage_blocker_scopes_follow_current_truth_across_scope_transfer(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=1_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("BTC-27SEP24-100010-C", expiry)
    second = make_option("BTC-27SEP24-100020-C", expiry)
    reducer.options = {
        first.instrument_name: first,
        second.instrument_name: second,
    }
    reducer.catalog_options = dict(reducer.options)
    assert reducer.clock is not None
    initial_timestamp = reducer.clock.interval_at(1_001).upper_ms
    for instrument in (first, second):
        reducer.trackers[instrument.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=instrument.instrument_name,
        )
        reducer.option_books[instrument.instrument_name] = make_book(
            instrument.instrument_name,
            "1",
        )
        reducer.tickers[instrument.instrument_name] = TickerState(
            Decimal(100),
            "index_price",
            initial_timestamp,
        )
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 0, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(first.instrument_name, second.instrument_name),
        countable=True,
    )

    second_refresh_ms = 1_500
    assert reducer._apply_ticker(
        second.instrument_name,
        {
            "instrument_name": second.instrument_name,
            "timestamp": reducer.clock.interval_at(second_refresh_ms).upper_ms,
            "underlying_price": 100,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 0, second_refresh_ms, 2),
    )

    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 0, 2_002, 3),
            CausalCause.OPTION_BOOK_FACT,
            failure_domain=FailureScope.OPTION,
            affected_scopes=(f"OPTION:{first.instrument_name}",),
        ),
        affected_instruments=(first.instrument_name,),
        countable=False,
    )
    assert reducer._coverage._current_affected_scopes == (f"OPTION:{first.instrument_name}",)

    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 0, 2_502, 4),
            CausalCause.OPTION_BOOK_FACT,
            failure_domain=FailureScope.OPTION,
            affected_scopes=(f"OPTION:{second.instrument_name}",),
        ),
        affected_instruments=(second.instrument_name,),
        countable=False,
    )
    assert reducer._coverage._current_affected_scopes == tuple(
        sorted(
            (
                f"OPTION:{first.instrument_name}",
                f"OPTION:{second.instrument_name}",
            )
        )
    )

    acknowledge_channel(reducer, ticker_channel(first.instrument_name), generation=1)
    recovery_ms = 2_503
    assert reducer._apply_ticker(
        first.instrument_name,
        {
            "instrument_name": first.instrument_name,
            "timestamp": reducer.clock.interval_at(recovery_ms).upper_ms,
            "underlying_price": 100,
            "underlying_index": "index_price",
        },
        FactBoundary(1, 0, recovery_ms, 5),
    )
    assert reducer._coverage._current_blocking_reason == "TICKER_SOURCE_STALE"
    assert reducer._coverage._current_affected_scopes == (f"OPTION:{second.instrument_name}",)


def test_clock_gap_is_a_concurrent_effect_of_original_market_fact_commit(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    captured_restart: list[CausalCommit] = []
    captured_coverage: list[CausalCommit] = []
    restart = reducer._restart_global_continuity
    transition = reducer._transition_coverage

    def fail_clock(_clock: TrustedClock, _monotonic_ms: int) -> TimeInterval:
        raise ContinuityGap("injected clock gap")

    def capture_restart(commit: CausalCommit, **kwargs: object) -> object:
        captured_restart.append(commit)
        return restart(commit, **kwargs)  # type: ignore[arg-type]

    def capture_transition(
        state: CoverageState,
        *,
        commit: CausalCommit,
        **kwargs: object,
    ) -> None:
        captured_coverage.append(commit)
        transition(state, commit=commit, **kwargs)  # type: ignore[arg-type]

    assert reducer.clock is not None
    monkeypatch.setattr(TrustedClock, "interval_at", fail_clock)
    monkeypatch.setattr(reducer, "_restart_global_continuity", capture_restart)
    monkeypatch.setattr(reducer, "_transition_coverage", capture_transition)
    original = CausalCommit(
        boundary=FactBoundary(1, 9, 1_100, 9),
        cause=CausalCause.OPTION_BOOK_CHANGED,
        failure_domain=FailureScope.OPTION,
        affected_scopes=("OPTION:SHORT",),
    )

    reducer.settle_fact(
        commit=original,
        affected_instruments=(),
        countable=False,
    )

    assert len(captured_restart) == len(captured_coverage) == 1
    frozen = captured_restart[0]
    assert captured_coverage[0] is frozen
    assert frozen.cause is CausalCause.OPTION_BOOK_CHANGED
    assert frozen.failure_domain is FailureScope.OPTION
    assert frozen.affected_scopes == ("OPTION:SHORT",)
    assert frozen.transaction_affected_scopes == ("GLOBAL",)
    assert tuple(
        (effect.cause, effect.failure_domain, effect.affected_scopes)
        for effect in frozen.concurrent_effects
    ) == ((CausalCause.CLOCK_GAP, FailureScope.CLOCK_INDEX, ("GLOBAL",)),)
