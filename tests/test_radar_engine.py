from __future__ import annotations

import math
from decimal import Decimal

from conftest import PolicyFactory
from market_monitor import ContinuousOrderBook, TimeInterval
from options_domain import AmountMetadata, OptionInstrument, OptionType
from short_vol_radar.black import black_price
from short_vol_radar.detector import DetectorState, EpisodeEndReason, EpisodeTracker, TrackerState
from short_vol_radar.policy import RadarPolicy, load_policy_bytes
from short_vol_radar.radar import TickerState, evaluate_instrument


def make_book(name: str, bid_price: Decimal | None, amount: str = "0.1") -> ContinuousOrderBook:
    bids = [] if bid_price is None else [["new", bid_price, amount]]
    book = ContinuousOrderBook(name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": name,
            "change_id": 1,
            "bids": bids,
            "asks": [],
        },
        1,
    )
    return book


def make_engine_inputs(
    policy_factory: PolicyFactory,
) -> tuple[RadarPolicy, OptionInstrument, EpisodeTracker, Decimal]:
    exact, digest = policy_factory(activation_count=1, clear_count=1, separation_ms=0)
    policy = load_policy_bytes(exact, digest)
    expiry = 60 * 60 * 1_000
    strike = Decimal("100.01")
    target_iv = 0.5
    time_years = 60 / (365 * 24 * 60)
    total_volatility = target_iv * math.sqrt(time_years)
    price = Decimal(str(black_price(100, float(strike), total_volatility, OptionType.CALL)))
    instrument = OptionInstrument(
        "SHORT",
        expiry,
        strike,
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=instrument.instrument_name,
    )
    return policy, instrument, tracker, price


def test_full_baseline_iv_delta_richness_path_can_activate(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, price = make_engine_inputs(policy_factory)
    result = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "BTC_USDC-27SEP24", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert result.known_evaluation
    assert result.full_formula_evaluation
    assert result.detector_state is DetectorState.ANOMALY_ACTIVE
    assert result.transition.activated_episode_id is not None
    assert result.calculation is not None
    assert result.calculation.richness.lower > Decimal("1.2")
    assert result.calculation.baseline.annualized_volatility == Decimal("0.1")


def test_known_liquidity_and_otm_failures_short_circuit_missing_inputs(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, _price = make_engine_inputs(policy_factory)
    depth = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", None),
        ticker=None,
        causal_closes=None,
    )
    assert depth.known_evaluation
    assert depth.reason == "INSUFFICIENT_TARGET_BID_DEPTH"
    assert depth.detector_state is DetectorState.NO_ANOMALY

    not_otm = OptionInstrument(
        "NOT_OTM",
        instrument.expiration_timestamp_ms,
        Decimal(99),
        OptionType.CALL,
        instrument.amount,
    )
    not_otm_tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=not_otm.instrument_name,
    )
    result = evaluate_instrument(
        policy=policy,
        tracker=not_otm_tracker,
        instrument=not_otm,
        trusted_time=TimeInterval(0, 0),
        causal_seq=2,
        option_book=make_book("NOT_OTM", Decimal(1)),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=None,
    )
    assert result.reason == "NOT_OTM"
    assert result.known_evaluation

    amount_unknown = OptionInstrument(
        "AMOUNT_UNKNOWN",
        instrument.expiration_timestamp_ms,
        instrument.strike,
        instrument.option_type,
        None,
    )
    amount_unknown_tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=amount_unknown.instrument_name,
    )
    no_depth = evaluate_instrument(
        policy=policy,
        tracker=amount_unknown_tracker,
        instrument=amount_unknown,
        trusted_time=TimeInterval(0, 0),
        causal_seq=3,
        option_book=make_book("AMOUNT_UNKNOWN", None),
        ticker=None,
        causal_closes=None,
    )
    assert no_depth.known_evaluation
    assert no_depth.reason == "INSUFFICIENT_TARGET_BID_DEPTH"

    with_depth = evaluate_instrument(
        policy=policy,
        tracker=amount_unknown_tracker,
        instrument=amount_unknown,
        trusted_time=TimeInterval(0, 0),
        causal_seq=4,
        option_book=make_book("AMOUNT_UNKNOWN", Decimal(1)),
        ticker=None,
        causal_closes=None,
    )
    assert not with_depth.known_evaluation
    assert with_depth.reason == "OPTION_AMOUNT_METADATA_UNKNOWN"


def test_missing_book_ticker_and_warmup_remain_unknown(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, price = make_engine_inputs(policy_factory)
    missing_book = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=None,
        ticker=None,
        causal_closes=None,
    )
    assert missing_book.detector_state is DetectorState.UNKNOWN
    assert not missing_book.known_evaluation

    missing_ticker = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=2,
        option_book=make_book("SHORT", price),
        ticker=None,
        causal_closes=None,
    )
    assert missing_ticker.reason == "FORWARD_TICKER_UNKNOWN"

    warmup = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=3,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=None,
    )
    assert "WARMUP" in (warmup.reason or "")
    assert warmup.detector_state is DetectorState.UNKNOWN


def test_band_boundary_suspends_but_scope_gap_ends_episode(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, price = make_engine_inputs(policy_factory)
    active = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert active.detector_state is DetectorState.ANOMALY_ACTIVE
    episode = tracker.episode_id

    six_hours = 6 * 60 * 60 * 1_000
    boundary_instrument = OptionInstrument(
        instrument.instrument_name,
        six_hours,
        instrument.strike,
        instrument.option_type,
        instrument.amount,
    )
    boundary = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=boundary_instrument,
        trusted_time=TimeInterval(-1, 1),
        causal_seq=2,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert boundary.reason == "TIME_BAND_BOUNDARY"
    assert tracker.state is TrackerState.BAND_SUSPENDED
    assert tracker.episode_id == episode

    final_window = OptionInstrument(
        instrument.instrument_name,
        30 * 60 * 1_000,
        instrument.strike,
        instrument.option_type,
        instrument.amount,
    )
    ended = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=final_window,
        trusted_time=TimeInterval(0, 0),
        causal_seq=3,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert ended.transition.ended_episode is not None
    assert ended.transition.ended_episode.reason is EpisodeEndReason.OUT_OF_BASELINE_SCOPE


def test_monitor_boundary_uncertainty_is_unknown_not_out_of_baseline_scope(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, price = make_engine_inputs(policy_factory)
    seventy_two_hours = 72 * 60 * 60 * 1_000
    boundary_instrument = OptionInstrument(
        instrument.instrument_name,
        seventy_two_hours,
        instrument.strike,
        instrument.option_type,
        instrument.amount,
    )
    result = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=boundary_instrument,
        trusted_time=TimeInterval(-1, 1),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert result.reason == "TIME_MONITOR_BOUNDARY"
    assert result.detector_state is DetectorState.UNKNOWN
