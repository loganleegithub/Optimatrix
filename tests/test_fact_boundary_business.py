from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from typing import cast

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
from short_vol_radar.black import DecimalInterval, black_price
from short_vol_radar.detector import (
    DetectorCoverage,
    DetectorObservation,
    DetectorState,
    EpisodeEndReason,
    EpisodeTracker,
)
from short_vol_radar.evidence import CoverageState, EvidenceWriter, validate_run_summary
from short_vol_radar.policy import RadarPolicy, load_policy_bytes
from short_vol_radar.radar import CurrentEvaluation, TickerState


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
    assert reducer._first_joint_witness_ms == monotonic_ms


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
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 2),
            CausalCause.INDEX_CONTINUITY_GAP,
        ),
        affected_instruments=(first.instrument_name,),
        countable=False,
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


def test_bootstrap_warmup_does_not_report_or_recover_a_real_index_gap(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
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

    assert reducer.results[instrument.instrument_name].reason == "INDEX_WARMUP"
    assert reducer.diagnostics.index_gap_count == 0
    assert not reducer._index_gap_active
    assert not reducer._index_resubscribe_pending


def test_minute_rollover_preserves_witness_through_recovery_and_summary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)
    known_ineligible = make_option(
        "BTC_USDC-27SEP24-100020-C",
        instrument.expiration_timestamp_ms,
    )
    out_of_scope = make_option(
        "BTC_USDC-27SEP24-100030-C",
        1_000_000 + 15 * 60_000,
    )
    for candidate in (known_ineligible, out_of_scope):
        reducer.options[candidate.instrument_name] = candidate
        reducer.catalog_options[candidate.instrument_name] = candidate
        reducer.trackers[candidate.instrument_name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=reducer.policy.identity,
            instrument_name=candidate.instrument_name,
        )
        reducer.option_books[candidate.instrument_name] = make_book(
            candidate.instrument_name,
            None,
        )

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

    assert reducer.results[instrument.instrument_name].reason == "INDEX_TIME_BOUNDARY_PENDING"
    assert reducer._first_joint_witness_ms == 1_001
    assert reducer._global_continuity_epoch == 1
    assert reducer.diagnostics.index_gap_count == 0

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

    assert reducer.results[instrument.instrument_name].reason == "INDEX_WATERMARK_PENDING"
    assert reducer._first_joint_witness_ms == 1_001
    assert reducer._global_continuity_epoch == 1
    assert reducer.diagnostics.index_gap_count == 0

    reducer._causal_seq = 4
    assert reducer._apply_index(
        {
            "timestamp": 1_020_000,
            "price": 100,
            "index_name": "btc_usdc",
        },
        FactBoundary(1, 4, 21_001, 4),
    )
    assert reducer.results[instrument.instrument_name].full_formula_evaluation
    assert reducer._first_joint_witness_ms == 1_001
    assert reducer._global_continuity_epoch == 1

    summary = json.loads(reducer.clean_stop(22_000).read_text())
    validate_run_summary(summary)
    assert summary["coverage"]["coverage_partition_error_ms"] == 0
    witness_band = reducer.results[instrument.instrument_name].band_id
    assert summary["operational_diagnostics"]["witness"] == {
        "global_continuity_epoch": 1,
        "first_joint_witness_monotonic_ms": 1_001,
        "continuous_global_continuity_after_witness_ms": 20_999,
        "scope": {
            "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
            "option_type": "call",
            "tte_band_id": witness_band,
        },
        "boundary": {
            "session_epoch": 1,
            "ingress_seq": 1,
            "received_monotonic_ms": 1_001,
            "causal_seq": 1,
        },
        "formula_instrument": {
            "instrument_name": instrument.instrument_name,
            "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
            "option_type": "call",
            "tte_band_id": witness_band,
        },
    }
    assert summary["operational_diagnostics"]["global_continuity"] == {
        "current_epoch": 1,
        "restart_count": 0,
        "restart_count_by_reason": {},
        "restart_edges": [],
    }
    assert {segment["global_continuity_epoch"] for segment in summary["coverage_segments"]} == {1}
    assert all(segment["reason"] for segment in summary["coverage_segments"])
    assert all(segment["affected_scopes"] for segment in summary["coverage_segments"])


def test_real_index_gap_requires_recovery_and_a_new_summary_witness(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    establish_joint_witness(reducer, instrument)

    reducer._causal_seq = 2
    assert not reducer._apply_index(
        {
            "timestamp": 900_000,
            "price": 100,
            "index_name": "btc_usdc",
        },
        FactBoundary(1, 2, 2_000, 2),
    )
    assert reducer._first_joint_witness_ms is None
    assert reducer._global_continuity_epoch == 2
    assert reducer.diagnostics.index_gap_count == 1
    assert reducer.platform.reason == "INDEX_CONTINUITY_GAP"

    reducer.index.start_continuous_coverage(1_020_000)
    for causal_seq, timestamp in enumerate(
        (1_020_001, 1_080_000, 1_140_000, 1_200_000, 1_260_000, 1_320_000, 1_380_000),
        start=10,
    ):
        reducer.index.accept_tick(
            source_timestamp_ms=timestamp,
            price=100,
            causal_seq=causal_seq,
        )
        reducer.index.seal_ready(timestamp)
    reducer._index_resubscribe_pending = False
    reducer.clock = TrustedClock.from_response(
        1_440_001,
        3_000,
        3_000,
        stale_deadline_ms=reducer.policy.runtime_limits.clock_stale_deadline_ms,
    )
    reducer.tickers[instrument.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_440_000,
    )
    reducer._causal_seq = 30
    assert reducer._apply_index(
        {
            "timestamp": 1_440_000,
            "price": 100,
            "index_name": "btc_usdc",
        },
        FactBoundary(1, 3, 3_000, 30),
    )

    assert reducer.results[instrument.instrument_name].full_formula_evaluation
    assert reducer._first_joint_witness_ms == 3_000
    assert reducer._global_continuity_epoch == 2
    assert not reducer._index_gap_active

    summary = json.loads(reducer.clean_stop(4_000).read_text())
    validate_run_summary(summary)
    witness_band = reducer.results[instrument.instrument_name].band_id
    assert summary["operational_diagnostics"]["witness"] == {
        "global_continuity_epoch": 2,
        "first_joint_witness_monotonic_ms": 3_000,
        "continuous_global_continuity_after_witness_ms": 1_000,
        "scope": {
            "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
            "option_type": "call",
            "tte_band_id": witness_band,
        },
        "boundary": {
            "session_epoch": 1,
            "ingress_seq": 3,
            "received_monotonic_ms": 3_000,
            "causal_seq": 30,
        },
        "formula_instrument": {
            "instrument_name": instrument.instrument_name,
            "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
            "option_type": "call",
            "tte_band_id": witness_band,
        },
    }
    assert summary["operational_diagnostics"]["global_continuity"] == {
        "current_epoch": 2,
        "restart_count": 1,
        "restart_count_by_reason": {"INDEX_CONTINUITY_GAP": 1},
        "restart_edges": [
            {
                "incident_id": 1,
                "from_epoch": 1,
                "to_epoch": 2,
                "reason": "INDEX_CONTINUITY_GAP",
                "failure_domain": "CLOCK_INDEX",
                "affected_scopes": ["GLOBAL"],
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 2,
                    "received_monotonic_ms": 2_000,
                    "causal_seq": 2,
                },
            }
        ],
    }
    coverage_epochs = [
        segment["global_continuity_epoch"] for segment in summary["coverage_segments"]
    ]
    assert coverage_epochs[0] == 1
    assert coverage_epochs[-1] == 2
    assert coverage_epochs == sorted(coverage_epochs)


def test_persistent_index_window_gap_restarts_global_continuity_once(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    instrument = make_option(
        "BTC_USDC-27SEP24-100010-C",
        1_000_000 + 60 * 60_000,
    )
    configure_full_formula_scope(reducer, instrument)
    reducer.index.start_continuous_coverage(0)
    monkeypatch.setattr(
        reducer.index,
        "current_tail",
        lambda *_args, **_kwargs: IndexTail(IndexTailStatus.WINDOW_GAP),
    )

    reducer._causal_seq = 1
    assert reducer._apply_index(
        {
            "timestamp": 1_000_000,
            "price": 100,
            "index_name": "btc_usdc",
        },
        FactBoundary(1, 1, 1_001, 1),
    )
    assert reducer._global_continuity_epoch == 2
    assert reducer.diagnostics.index_gap_count == 1
    assert reducer._coverage._current_reason == "INDEX_WINDOW_GAP"
    assert reducer._coverage._current_affected_scopes == (
        f"SCOPE:{instrument.expiration_timestamp_ms}:call:{reducer.policy.tte_bands[0].band_id}",
    )

    reducer._causal_seq = 2
    assert reducer._apply_index(
        {
            "timestamp": 1_000_001,
            "price": 100,
            "index_name": "btc_usdc",
        },
        FactBoundary(1, 2, 1_002, 2),
    )
    assert reducer._global_continuity_epoch == 2
    assert reducer.diagnostics.index_gap_count == 1


def test_joint_witness_uses_full_current_scope_for_coverage_and_formula(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    full_formula = make_option("BTC_USDC-27SEP24-100010-C", expiry)
    known_ineligible = make_option("BTC_USDC-27SEP24-100020-C", expiry)
    configure_full_formula_scope(reducer, full_formula)
    reducer.options[known_ineligible.instrument_name] = known_ineligible
    reducer.catalog_options = dict(reducer.options)
    reducer.trackers[known_ineligible.instrument_name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=reducer.policy.identity,
        instrument_name=known_ineligible.instrument_name,
    )
    reducer.option_books[known_ineligible.instrument_name] = make_book(
        known_ineligible.instrument_name,
        None,
    )
    reducer.tickers[known_ineligible.instrument_name] = TickerState(
        Decimal(100),
        "index_price",
        1_000_000,
    )
    reducer._causal_seq = 1
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=tuple(reducer.options),
        countable=True,
    )

    assert reducer.results[full_formula.instrument_name].full_formula_evaluation
    assert reducer.results[known_ineligible.instrument_name].known_evaluation
    assert not reducer.results[known_ineligible.instrument_name].full_formula_evaluation
    assert reducer._coverage._current_state is CoverageState.KNOWN_COMPLETE
    assert reducer._first_joint_witness_ms == 1_001
    counter = next(iter(reducer._scope_counts.values()))
    full_scope_count = counter.complete_aggregate_with_full_formula_evaluation_count

    reducer._first_joint_witness_ms = None
    reducer._first_joint_witness_identity = None
    reducer._causal_seq = 2
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 1_002, 2),
            CausalCause.OPTION_BOOK_CHANGED,
            failure_domain=FailureScope.OPTION,
            affected_scopes=(f"OPTION:{known_ineligible.instrument_name}",),
        ),
        affected_instruments=(known_ineligible.instrument_name,),
        countable=False,
    )

    assert reducer._coverage._current_state is CoverageState.KNOWN_COMPLETE
    assert reducer._first_joint_witness_ms == 1_002
    assert counter.complete_aggregate_with_full_formula_evaluation_count == full_scope_count + 1


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
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(unknown.instrument_name,),
        countable=True,
    )
    assert reducer.trackers[unknown.instrument_name].detector_state is DetectorState.UNKNOWN

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
        "BTC_USDC-27SEP24-100010-C",
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
    witness = reducer._first_joint_witness_ms
    coverage_state = reducer._coverage._current_state
    coverage_start = reducer._coverage._current_start_ms
    anomaly_files = tuple(tmp_path.glob("short-vol-anomaly-*.json"))

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
    assert reducer.results[name] is result
    assert reducer.trackers[name].episode_id == episode_id
    assert reducer._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 0
    assert reducer._first_joint_witness_ms == witness
    assert reducer._coverage._current_state is coverage_state
    assert reducer._coverage._current_start_ms == coverage_start
    assert tuple(tmp_path.glob("short-vol-anomaly-*.json")) == anomaly_files
    assert not reducer._channels[channel].resync_requested
    assert reducer.diagnostics.option_channel_resync_count == 0
    diagnostics = reducer._operational_diagnostics(2)
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(source_shapes, list)
    source_row = next(
        row for row in source_shapes if isinstance(row, dict) and row["source"] == "option_ticker"
    )
    assert source_row["valid_count"] == 1
    assert source_row["invalid_count"] == 0
    ticker_application = diagnostics["ticker_application"]
    assert isinstance(ticker_application, dict)
    disposition_count = ticker_application["disposition_count"]
    assert isinstance(disposition_count, dict)
    assert disposition_count["LATE_IGNORED"] == 1
    assert ticker_application["late_ignored_diagnostics"] == [
        {
            "instrument_name": name,
            "generation": 7,
            "ingress_seq": 1,
            "previous_source_timestamp_ms": accepted.source_timestamp_ms,
            "candidate_source_timestamp_ms": accepted.source_timestamp_ms - 1,
            "timestamp_delta_ms": -1,
            "received_monotonic_ms": 1_002,
            "disposition": "LATE_IGNORED",
        }
    ]


def test_equal_ticker_timestamp_applies_in_later_ingress_order(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC_USDC-27SEP24-100010-C"
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
    diagnostics = reducer._operational_diagnostics(2)
    ticker_application = diagnostics["ticker_application"]
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(ticker_application, dict)
    assert isinstance(source_shapes, list)
    disposition_count = ticker_application["disposition_count"]
    assert isinstance(disposition_count, dict)
    assert disposition_count["APPLIED"] == 1
    source_row = next(
        row for row in source_shapes if isinstance(row, dict) and row["source"] == "option_ticker"
    )
    assert source_row["valid_count"] == 1


def test_older_ticker_is_late_ignored_even_when_candidate_timestamp_is_ahead(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=300_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC_USDC-27SEP24-100010-C"
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
    diagnostics = reducer._operational_diagnostics(1_000)
    ticker_currentness = diagnostics["ticker_currentness"]
    ticker_application = diagnostics["ticker_application"]
    assert isinstance(ticker_currentness, dict)
    assert isinstance(ticker_application, dict)
    assert ticker_currentness["candidate_count_by_classification"] == {
        "CURRENT": 0,
        "SOURCE_STALE": 0,
        "TIMESTAMP_AHEAD": 1,
        "TRUSTED_TIME_UNKNOWN": 0,
    }
    assert ticker_application["disposition_count"] == {
        "APPLIED": 0,
        "LATE_IGNORED": 1,
        "AHEAD_IGNORED": 0,
        "STALE_GENERATION_IGNORED": 0,
        "SHAPE_REJECTED": 0,
    }


def test_ticker_candidate_without_trusted_time_is_not_classified_current(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC_USDC-27SEP24-100010-C"
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

    diagnostics = reducer._operational_diagnostics(1)
    ticker_currentness = diagnostics["ticker_currentness"]
    ticker_application = diagnostics["ticker_application"]
    assert isinstance(ticker_currentness, dict)
    assert isinstance(ticker_application, dict)
    assert ticker_currentness["candidate_count_by_classification"] == {
        "CURRENT": 0,
        "SOURCE_STALE": 0,
        "TIMESTAMP_AHEAD": 0,
        "TRUSTED_TIME_UNKNOWN": 1,
    }
    assert ticker_application["disposition_count"]["APPLIED"] == 1
    assert reducer._coverage._current_state is CoverageState.UNKNOWN
    assert reducer._global_continuity_epoch == 1


def test_latched_stale_generation_candidate_is_not_counted_as_timestamp_regression(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=1_000)
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    name = "BTC_USDC-27SEP24-100010-C"
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
    diagnostics = reducer._operational_diagnostics(1_002)
    ticker_application = diagnostics["ticker_application"]
    assert isinstance(ticker_application, dict)
    disposition_count = ticker_application["disposition_count"]
    assert isinstance(disposition_count, dict)
    assert disposition_count["STALE_GENERATION_IGNORED"] == 1
    assert disposition_count["LATE_IGNORED"] == 0
    assert ticker_application["late_ignored_diagnostics"] == []


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
        commit=fact_commit(
            FactBoundary(1, 0, 1_001, 1),
            CausalCause.INDEX_TICK,
        ),
        affected_instruments=(name,),
        countable=True,
    )
    assert reducer._first_joint_witness_ms == 1_001
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
    assert reducer._first_joint_witness_ms == 1_001
    assert reducer._global_continuity_epoch == 1
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
    assert reducer._first_joint_witness_ms == 1_001
    assert reducer._global_continuity_epoch == 1

    summary = json.loads(reducer.clean_stop(2_100).read_text())
    validate_run_summary(summary)
    witness_band = reducer.results[name].band_id
    assert summary["operational_diagnostics"]["witness"] == {
        "global_continuity_epoch": 1,
        "first_joint_witness_monotonic_ms": 1_001,
        "continuous_global_continuity_after_witness_ms": 1_099,
        "scope": {
            "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
            "option_type": "call",
            "tte_band_id": witness_band,
        },
        "boundary": {
            "session_epoch": 1,
            "ingress_seq": 0,
            "received_monotonic_ms": 1_001,
            "causal_seq": 1,
        },
        "formula_instrument": {
            "instrument_name": name,
            "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
            "option_type": "call",
            "tte_band_id": witness_band,
        },
    }
    assert summary["operational_diagnostics"]["option_local_availability"] == {
        "unavailable_count_by_reason": {"TICKER_SOURCE_STALE": 1},
        "recovery_count_by_reason": {"TICKER_SOURCE_STALE": 1},
        "end_count_by_disposition": {
            "RECOVERED": 1,
            "REASON_CHANGED": 0,
            "CENSORED_AT_STOP": 0,
        },
        "retained_interval_limit": 256,
        "omitted_interval_count": 0,
        "omitted_interval_count_by_reason": {},
        "intervals": [
            {
                "instrument_name": name,
                "generation": 1,
                "reason": "TICKER_SOURCE_STALE",
                "start_monotonic_ms": 2_000,
                "end_monotonic_ms": 2_003,
                "duration_ms": 3,
                "end_disposition": "RECOVERED",
                "global_continuity_epoch": 1,
            }
        ],
    }
    stale_coverage = next(
        segment
        for segment in summary["coverage_segments"]
        if segment["reason"] == "TICKER_SOURCE_STALE"
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
        commit=fact_commit(
            FactBoundary(1, 0, 1_000, 1),
            CausalCause.INDEX_TICK,
        ),
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
        "BTC_USDC-27SEP24-100010-C",
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
    witness = reducer._first_joint_witness_ms
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
    assert reducer.results[name] is result
    assert reducer.trackers[name].episode_id == episode_id
    assert reducer._first_joint_witness_ms == witness
    assert name not in reducer._ticker_currentness_latches
    assert not reducer._channels[channel].resync_requested
    assert reducer.diagnostics.option_channel_resync_count == 0
    diagnostics = reducer._operational_diagnostics(3)
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(source_shapes, list)
    source_row = next(
        row for row in source_shapes if isinstance(row, dict) and row["source"] == "option_ticker"
    )
    assert source_row["valid_count"] == 1
    assert source_row["invalid_count"] == 1
    ticker_currentness = diagnostics["ticker_currentness"]
    ticker_application = diagnostics["ticker_application"]
    assert isinstance(ticker_currentness, dict)
    assert isinstance(ticker_application, dict)
    assert ticker_currentness["candidate_count_by_classification"] == {
        "CURRENT": 0,
        "SOURCE_STALE": 0,
        "TIMESTAMP_AHEAD": 1,
        "TRUSTED_TIME_UNKNOWN": 0,
    }
    assert ticker_application["disposition_count"] == {
        "APPLIED": 0,
        "LATE_IGNORED": 0,
        "AHEAD_IGNORED": 1,
        "STALE_GENERATION_IGNORED": 0,
        "SHAPE_REJECTED": 1,
    }


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
        commit=fact_commit(
            FactBoundary(1, 1, 1_001, 2),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
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
    reducer.option_books["SECOND"] = make_book("SECOND", "1")
    reducer.tickers = {
        "FIRST": TickerState(Decimal(100), "index_price", 1_000_001),
        "SECOND": TickerState(Decimal(100), "index_price", 1_000_001),
    }
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

    reducer.index.gap()
    reducer.settle_fact(
        commit=fact_commit(
            FactBoundary(1, 2, 2_000, 3),
            CausalCause.INDEX_CONTINUITY_GAP,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
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
        commit=fact_commit(
            FactBoundary(1, 1, 1_500, 2),
            CausalCause.TIME_BOUNDARY,
        ),
        affected_instruments=(instrument.instrument_name,),
        countable=False,
    )
    monkeypatch.setattr(reducer.index, "current_tail", original_current_tail)
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

    assert reducer._known_active_duration_ms[EpisodeEndReason.CENSORED_AT_STOP.value] == 1_000


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
        runtime_module.CoverageLedger(0)  # type: ignore[call-arg]


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
    assert sum(reducer.diagnostics.global_continuity_restart_count.values()) == 1

    reducer._recover_continuity_incident(incident)
    later_commit = CausalCommit(
        boundary=FactBoundary(1, 2, 2_001, 2),
        cause=CausalCause.INDEX_CONTINUITY_GAP,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )
    later_incident = reducer._restart_global_continuity(later_commit)

    assert later_incident != incident
    assert reducer._global_continuity_epoch == 3
    assert sum(reducer.diagnostics.global_continuity_restart_count.values()) == 2


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
        {"timestamp": "invalid", "price": 100, "index_name": "btc_usdc"},
        FactBoundary(1, 3, 1_003, 3),
    )
    assert reducer._active_continuity_incident is incident
    assert reducer._global_continuity_epoch == 2
    assert sum(reducer.diagnostics.global_continuity_restart_count.values()) == 1


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
        "BTC_USDC-27SEP24-100010-C",
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
        "BTC_USDC-27SEP24-100010-C",
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
    requests_before = dict(reducer.diagnostics.rpc_request_count)

    newly_stale = reducer.settle_source_currentness(FactBoundary(1, 1, 2_001, 1))

    assert newly_stale == (instrument.instrument_name,)
    assert tuple(reducer.pending_rpcs) == pending_before
    assert dict(reducer.diagnostics.rpc_request_count) == requests_before


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
    assert reducer._apply_book(
        first.instrument_name,
        {
            "type": "change",
            "timestamp": 2,
            "instrument_name": first.instrument_name,
            "change_id": 2,
            "prev_change_id": 1,
            "bids": [["new", "999", "0.1"]],
            "asks": [],
        },
        FactBoundary(1, 2, 2_001, 2),
    )

    assert reducer._settled_ticker_currentness[second.instrument_name].state.value == "SOURCE_STALE"
    assert reducer.results[second.instrument_name].reason == "TICKER_SOURCE_STALE"


def test_scope_snapshot_contains_only_every_current_member_of_one_scope(
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
    current_scope_truth = reducer._current_scope_truth

    def capture_snapshot(snapshot: ScopeSnapshot) -> object:
        captured.append(snapshot)
        return current_scope_truth(snapshot)

    monkeypatch.setattr(reducer, "_current_scope_truth", capture_snapshot)
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
    assert tuple(item.instrument.instrument_name for item in snapshot.current) == (
        "FIRST",
        "SECOND",
    )
    assert all(item.result is not None for item in snapshot.current)

    before = current_scope_truth(snapshot)
    reducer.options.clear()
    reducer.trackers.clear()
    reducer.results.clear()
    after = current_scope_truth(snapshot)
    assert after == before


def test_option_lifecycle_unknown_recomputes_aggregate_from_one_full_scope_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    reducer = make_reducer(tmp_path, load_policy_bytes(exact, digest))
    seed_flat_available_index(reducer)
    expiry = 1_000_000 + 60 * 60_000
    first = make_option("FIRST", expiry)
    second = make_option("SECOND", expiry)
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
        "FIRST",
        "SECOND",
    )
    assert reducer.results[first.instrument_name].reason == "OPTION_LIFECYCLE_HALTED"
    aggregate = next(iter(reducer.aggregate_results.values()))
    assert aggregate.coverage is DetectorCoverage.UNKNOWN
