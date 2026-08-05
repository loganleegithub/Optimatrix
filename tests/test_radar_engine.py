from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal

import pytest
import short_vol_radar.radar as radar_module
from conftest import PolicyFactory, encode_policy, policy_document
from market_monitor import ContinuousOrderBook, TimeInterval
from options_domain import AmountMetadata, OptionInstrument, OptionType, PriceTickMetadata
from short_vol_radar.black import black_price
from short_vol_radar.detector import (
    DetectorState,
    EpisodeEndReason,
    EpisodeTracker,
    TrackerState,
)
from short_vol_radar.policy import RadarPolicy, load_policy_bytes
from short_vol_radar.radar import (
    CurrentDisposition,
    TickerState,
    calculate_current_evaluation,
    evaluate_instrument,
    parse_ticker,
)

TEST_PRICE_TICK = PriceTickMetadata(Decimal("0.00000001"))


def make_book(
    name: str,
    bid_price: Decimal | None,
    amount: str = "0.1",
    *,
    include_ask: bool = True,
) -> ContinuousOrderBook:
    bids = [] if bid_price is None else [["new", bid_price, amount]]
    asks = (
        []
        if bid_price is None or not include_ask
        else [["new", bid_price + Decimal("0.00000002"), amount]]
    )
    book = ContinuousOrderBook(name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": name,
            "change_id": 1,
            "bids": bids,
            "asks": asks,
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
        TEST_PRICE_TICK,
    )
    tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=instrument.instrument_name,
    )
    return policy, instrument, tracker, price


def test_ticker_forward_basis_must_match_the_option_expiry_future_or_index() -> None:
    instrument_name = "BTC_USDC-27SEP24-110000-C"
    common = {
        "instrument_name": instrument_name,
        "timestamp": 1,
        "underlying_price": 100,
    }

    assert (
        parse_ticker(
            {**common, "underlying_index": "index_price"}, instrument_name
        ).underlying_index
        == "index_price"
    )
    assert (
        parse_ticker(
            {**common, "underlying_index": "BTC_USDC-27SEP24"}, instrument_name
        ).underlying_index
        == "BTC_USDC-27SEP24"
    )

    for invalid_basis in ("BTC_USDC-26SEP24", "BTC-27SEP24", "garbage"):
        with pytest.raises(ValueError, match="forward basis"):
            parse_ticker({**common, "underlying_index": invalid_basis}, instrument_name)


def test_ticker_preserves_official_signed_delta_and_normalizes_mark_iv() -> None:
    instrument_name = "BTC_USDC-27SEP24-110000-C"
    common = {
        "instrument_name": instrument_name,
        "timestamp": 1,
        "underlying_price": 100,
        "underlying_index": "index_price",
    }

    ticker = parse_ticker(
        {
            **common,
            "greeks": {"delta": "-0.375"},
            "mark_iv": "52.125",
        },
        instrument_name,
    )

    assert ticker.signed_delta == Decimal("-0.375")
    assert ticker.mark_iv_fraction == Decimal("0.52125")
    missing = parse_ticker(common, instrument_name)
    assert missing.signed_delta is None
    assert missing.mark_iv_fraction is None


@pytest.mark.parametrize(
    "delta",
    [True, "malformed", "NaN", "Infinity", "-Infinity", "1.0000001", "-1.0000001"],
)
def test_ticker_invalid_official_delta_is_unknown_without_hiding_valid_mark_iv(
    delta: object,
) -> None:
    instrument_name = "BTC_USDC-27SEP24-110000-C"

    ticker = parse_ticker(
        {
            "instrument_name": instrument_name,
            "timestamp": 1,
            "underlying_price": 100,
            "underlying_index": "index_price",
            "greeks": {"delta": delta},
            "mark_iv": "50",
        },
        instrument_name,
    )

    assert ticker.signed_delta is None
    assert ticker.mark_iv_fraction == Decimal("0.5")


@pytest.mark.parametrize(
    "mark_iv",
    [True, "malformed", "NaN", "Infinity", "-Infinity", "-0.0001"],
)
def test_ticker_invalid_mark_iv_is_unknown_without_hiding_valid_delta(
    mark_iv: object,
) -> None:
    instrument_name = "BTC_USDC-27SEP24-110000-C"

    ticker = parse_ticker(
        {
            "instrument_name": instrument_name,
            "timestamp": 1,
            "underlying_price": 100,
            "underlying_index": "index_price",
            "greeks": {"delta": "-0.25"},
            "mark_iv": mark_iv,
        },
        instrument_name,
    )

    assert ticker.signed_delta == Decimal("-0.25")
    assert ticker.mark_iv_fraction is None


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


def test_hard_screen_requires_target_ask_and_official_tick_metadata(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, price = make_engine_inputs(policy_factory)
    no_ask = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price, include_ask=False),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert no_ask.reason == "INSUFFICIENT_TARGET_ASK_DEPTH"
    assert no_ask.detector_state is DetectorState.NO_ANOMALY

    missing_tick = replace(instrument, price_tick=None)
    missing_tick_tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=missing_tick.instrument_name,
    )
    unknown = evaluate_instrument(
        policy=policy,
        tracker=missing_tick_tracker,
        instrument=missing_tick,
        trusted_time=TimeInterval(0, 0),
        causal_seq=2,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert unknown.reason == "OPTION_PRICE_TICK_METADATA_UNKNOWN"
    assert unknown.detector_state is DetectorState.UNKNOWN


def test_activation_uses_one_tick_stressed_richness_not_raw_richness(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(
        activation=1.2,
        activation_count=1,
        clear_count=1,
        separation_ms=0,
    )
    policy = load_policy_bytes(exact, digest)
    expiry = 60 * 60 * 1_000
    strike = Decimal("100.01")
    raw_iv = 0.13
    total_volatility = raw_iv * math.sqrt(60 / (365 * 24 * 60))
    price = Decimal(str(black_price(100, float(strike), total_volatility, OptionType.CALL)))
    instrument = OptionInstrument(
        "SHORT",
        expiry,
        strike,
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
        PriceTickMetadata(price * Decimal("0.20")),
    )
    tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=instrument.instrument_name,
    )
    result = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    assert result.calculation is not None
    assert result.calculation.raw_richness.lower >= Decimal("1.2")
    assert result.calculation.richness.upper < Decimal("1.2")
    assert result.detector_state is DetectorState.NO_ANOMALY
    assert result.transition.activated_episode_id is None


def test_clock_only_recalculation_is_not_a_countable_persistence_observation(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=2, clear_count=2, separation_ms=0)
    policy = load_policy_bytes(exact, digest)
    expiry = 60 * 60 * 1_000
    strike = Decimal("100.01")
    total_volatility = 0.5 * math.sqrt(60 / (365 * 24 * 60))
    price = Decimal(str(black_price(100, float(strike), total_volatility, OptionType.CALL)))
    instrument = OptionInstrument(
        "SHORT",
        expiry,
        strike,
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
        TEST_PRICE_TICK,
    )
    tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=instrument.instrument_name,
    )
    book = make_book("SHORT", price)
    ticker = TickerState(Decimal(100), "index_price", 1)
    closes = (Decimal(100),) * 6

    first = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=book,
        ticker=ticker,
        causal_closes=closes,
        observation_eligible=True,
        observation_reason=None,
    )
    clock_only = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(1_000, 1_000),
        causal_seq=2,
        option_book=book,
        ticker=ticker,
        causal_closes=closes,
        observation_eligible=False,
        observation_reason="CLOCK_ONLY",
    )

    assert first.known_evaluation
    assert clock_only.known_evaluation
    assert not clock_only.observation_eligible
    assert clock_only.observation_reason == "CLOCK_ONLY"
    assert tracker.detector_state is DetectorState.NO_ANOMALY
    assert tracker.episode_id is None


def test_current_hard_ineligibility_ends_active_episode_even_when_not_countable(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, price = make_engine_inputs(policy_factory)
    activated = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    episode_id = tracker.episode_id
    assert activated.detector_state is DetectorState.ANOMALY_ACTIVE

    current = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(1_000, 1_000),
        causal_seq=2,
        option_book=make_book("SHORT", None),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
        observation_eligible=False,
        observation_reason="CLOCK_ONLY",
    )

    assert current.reason == "INSUFFICIENT_TARGET_BID_DEPTH"
    assert not current.observation_eligible
    assert current.observation_reason == "CLOCK_ONLY"
    assert tracker.detector_state is DetectorState.NO_ANOMALY
    assert tracker.episode_id is None
    assert current.transition.ended_episode is not None
    assert current.transition.ended_episode.episode_id == episode_id
    assert current.transition.ended_episode.reason is EpisodeEndReason.KNOWN_INELIGIBLE


def test_known_empty_book_recovers_unknown_to_no_anomaly_without_countability(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, tracker, _price = make_engine_inputs(policy_factory)
    unknown = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=None,
        ticker=None,
        causal_closes=None,
        observation_eligible=True,
    )
    known_empty = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=2,
        option_book=make_book("SHORT", None),
        ticker=None,
        causal_closes=None,
        observation_eligible=False,
        observation_reason="DUPLICATE_REDUCED_STATE",
    )

    assert unknown.detector_state is DetectorState.UNKNOWN
    assert known_empty.reason == "INSUFFICIENT_TARGET_BID_DEPTH"
    assert known_empty.known_evaluation
    assert not known_empty.observation_eligible
    assert known_empty.detector_state is DetectorState.NO_ANOMALY
    assert tracker.state is TrackerState.ARMED


@pytest.mark.parametrize(
    ("replacement_amount", "expected_reason", "expected_end"),
    [
        (None, "OPTION_AMOUNT_METADATA_UNKNOWN", EpisodeEndReason.UNKNOWN_DETECTOR),
        (
            AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.3")),
            "OFF_PUBLISHED_QUANTITY_GRID",
            EpisodeEndReason.KNOWN_INELIGIBLE,
        ),
    ],
)
def test_current_amount_loss_ends_active_episode_without_countability(
    policy_factory: PolicyFactory,
    replacement_amount: AmountMetadata | None,
    expected_reason: str,
    expected_end: EpisodeEndReason,
) -> None:
    policy, instrument, tracker, price = make_engine_inputs(policy_factory)
    activated = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
    )
    episode_id = tracker.episode_id
    assert activated.detector_state is DetectorState.ANOMALY_ACTIVE
    assert episode_id is not None

    current = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=replace(instrument, amount=replacement_amount),
        trusted_time=TimeInterval(0, 0),
        causal_seq=2,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100),) * 6,
        observation_eligible=False,
        observation_reason="DUPLICATE_REDUCED_STATE",
    )

    assert current.reason == expected_reason
    assert current.transition.ended_episode is not None
    assert current.transition.ended_episode.episode_id == episode_id
    assert current.transition.ended_episode.reason is expected_end
    assert tracker.episode_id is None


def test_observation_identity_ignores_ask_and_depth_beyond_target(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, _tracker, price = make_engine_inputs(policy_factory)
    book = ContinuousOrderBook(instrument.instrument_name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": instrument.instrument_name,
            "change_id": 1,
            "bids": [
                ["new", price, "0.1"],
                ["new", price / 2, "1.0"],
            ],
            "asks": [["new", price * 2, "1.0"]],
        },
        1,
    )
    ticker = TickerState(Decimal(100), "index_price", 1)
    baseline_identity = (0, (Decimal(100),) * 6)
    first = radar_module.detector_observation_identity(
        policy=policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        option_book=book,
        ticker=ticker,
        baseline_identity=baseline_identity,
    )

    book.apply(
        {
            "type": "change",
            "timestamp": 2,
            "instrument_name": instrument.instrument_name,
            "change_id": 2,
            "prev_change_id": 1,
            "bids": [["change", price / 2, "2.0"]],
            "asks": [["change", price * 2, "2.0"]],
        },
        2,
    )
    after_unconsumed_change = radar_module.detector_observation_identity(
        policy=policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        option_book=book,
        ticker=ticker,
        baseline_identity=baseline_identity,
    )
    after_forward_basis_label_change = radar_module.detector_observation_identity(
        policy=policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        option_book=book,
        ticker=TickerState(Decimal(100), "BTC_USDC-27SEP24", 2),
        baseline_identity=baseline_identity,
    )

    assert first == after_unconsumed_change
    assert first == after_forward_basis_label_change

    after_unconsumed_risk_projection_change = radar_module.detector_observation_identity(
        policy=policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        option_book=book,
        ticker=TickerState(
            Decimal(100),
            "index_price",
            3,
            signed_delta=Decimal("-0.75"),
            mark_iv_fraction=Decimal("0.8"),
        ),
        baseline_identity=baseline_identity,
    )
    assert first == after_unconsumed_risk_projection_change


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
        instrument.price_tick,
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
        instrument.price_tick,
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


def test_insufficient_depth_short_circuits_stale_ticker_unknown(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, _tracker, _price = make_engine_inputs(policy_factory)

    current = calculate_current_evaluation(
        policy=policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", None),
        ticker=None,
        causal_closes=None,
        ticker_unavailable_reason="TICKER_SOURCE_STALE",
        ticker_continuity_gap=True,
    )

    assert current.disposition is CurrentDisposition.KNOWN_INELIGIBLE
    assert current.reason == "INSUFFICIENT_TARGET_BID_DEPTH"
    assert current.known_evaluation
    assert not current.continuity_gap


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


@pytest.mark.parametrize(
    ("reason", "expected_disposition", "expected_continuity_gap"),
    [
        ("INDEX_WARMUP", CurrentDisposition.UNKNOWN, False),
        ("INDEX_WINDOW_GAP", CurrentDisposition.UNKNOWN, True),
        ("INDEX_SOURCE_STALE", CurrentDisposition.UNKNOWN, True),
        ("INDEX_CONTINUITY_GAP", CurrentDisposition.UNKNOWN, True),
        ("INDEX_HISTORY_SOURCE_STALE", CurrentDisposition.UNKNOWN, True),
        ("INDEX_HISTORY_WINDOW_GAP", CurrentDisposition.UNKNOWN, True),
        ("INDEX_HISTORY_REVISION", CurrentDisposition.UNKNOWN, True),
    ],
)
def test_index_tail_unavailability_has_typed_current_semantics(
    policy_factory: PolicyFactory,
    reason: str,
    expected_disposition: CurrentDisposition,
    expected_continuity_gap: bool,
) -> None:
    policy, instrument, _tracker, price = make_engine_inputs(policy_factory)

    current = calculate_current_evaluation(
        policy=policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=None,
        baseline_unavailable_reason=reason,
    )

    assert current.reason == reason
    assert current.disposition is expected_disposition
    assert current.continuity_gap is expected_continuity_gap
    assert not current.known_evaluation
    assert not current.full_formula_evaluation


def test_index_unavailability_is_lazy_behind_pricing_eligibility_gates(
    policy_factory: PolicyFactory,
) -> None:
    policy, instrument, _tracker, price = make_engine_inputs(policy_factory)
    unavailable = "INDEX_CONTINUITY_GAP"

    def current(
        candidate: OptionInstrument,
        option_book: ContinuousOrderBook | None,
        ticker: TickerState | None,
    ) -> radar_module.CurrentEvaluation:
        return calculate_current_evaluation(
            policy=policy,
            instrument=candidate,
            trusted_time=TimeInterval(0, 0),
            causal_seq=1,
            option_book=option_book,
            ticker=ticker,
            causal_closes=None,
            baseline_unavailable_reason=unavailable,
        )

    valid_book = make_book("SHORT", price)
    valid_ticker = TickerState(Decimal(100), "index_price", 1)
    amount_ineligible = current(
        replace(
            instrument,
            amount=AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.3")),
        ),
        None,
        None,
    )
    book_unknown = current(instrument, None, None)
    depth_ineligible = current(instrument, make_book("SHORT", None), None)
    ticker_unknown = current(instrument, valid_book, None)
    not_otm = current(
        replace(instrument, strike=Decimal(99)),
        valid_book,
        valid_ticker,
    )
    assert amount_ineligible.reason == "OFF_PUBLISHED_QUANTITY_GRID"
    assert book_unknown.reason == "OPTION_BOOK_UNKNOWN"
    assert depth_ineligible.reason == "INSUFFICIENT_TARGET_BID_DEPTH"
    assert ticker_unknown.reason == "FORWARD_TICKER_UNKNOWN"
    assert not_otm.reason == "NOT_OTM"


def test_near_atm_delta_is_review_only_and_cannot_activate_a_radar_clue() -> None:
    document = policy_document(activation_count=1, clear_count=1, separation_ms=0)
    bands = document["tte_bands"]
    assert isinstance(bands, list)
    for band in bands:
        assert isinstance(band, dict)
        rules = band["option_rules"]
        assert isinstance(rules, dict)
        for rule in rules.values():
            assert isinstance(rule, dict)
            rule["abs_delta_max"] = 0.4
    exact, digest = encode_policy(document)
    policy = load_policy_bytes(exact, digest)
    strike = Decimal("100.01")
    total_volatility = 0.5 * math.sqrt(60 / (365 * 24 * 60))
    price = Decimal(str(black_price(100, float(strike), total_volatility, OptionType.CALL)))
    instrument = OptionInstrument(
        "SHORT",
        60 * 60 * 1_000,
        strike,
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
        TEST_PRICE_TICK,
    )
    tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=instrument.instrument_name,
    )

    result = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100), Decimal(100)),
    )

    assert result.current_evaluation is not None
    assert result.current_evaluation.disposition is CurrentDisposition.REVIEW_ONLY
    assert result.reason == "REVIEW_ONLY_DELTA_BUCKET"
    assert result.calculation is not None
    assert result.calculation.delta_bucket.value == "ATM_GT_40"
    assert not result.calculation.delta_clue_eligible
    assert not result.calculation.clue_eligible
    assert result.detector_state is DetectorState.NO_ANOMALY
    assert result.transition.activated_episode_id is None


def test_30_to_45_minute_tte_is_review_only_and_cannot_activate(
    policy_factory: PolicyFactory,
) -> None:
    document = policy_document(activation_count=1, clear_count=1, separation_ms=0)
    bands = document["tte_bands"]
    assert isinstance(bands, list)
    first_band = bands[0]
    second_band = bands[1]
    assert isinstance(first_band, dict)
    assert isinstance(second_band, dict)
    first_band["lower_bound_minutes"] = 30
    first_band["upper_bound_minutes"] = 45
    first_band["clue_eligible"] = False
    second_band["lower_bound_minutes"] = 45
    exact, digest = encode_policy(document)
    policy = load_policy_bytes(exact, digest)
    _unused, instrument, _tracker, price = make_engine_inputs(policy_factory)
    instrument = replace(instrument, expiration_timestamp_ms=40 * 60 * 1_000)
    tracker = EpisodeTracker(
        runtime_identity="run",
        policy_identity=policy.identity,
        instrument_name=instrument.instrument_name,
    )

    result = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=(Decimal(100), Decimal(100)),
    )

    assert result.reason == "REVIEW_ONLY_TTE_BAND"
    assert result.current_evaluation is not None
    assert result.current_evaluation.disposition is CurrentDisposition.REVIEW_ONLY
    assert result.calculation is not None
    assert not result.calculation.clue_eligible
    assert result.detector_state is DetectorState.NO_ANOMALY
    assert result.transition.activated_episode_id is None


def test_history_revision_ends_an_active_episode_as_a_gap(
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
        causal_closes=(Decimal(100), Decimal(100)),
    )
    assert active.detector_state is DetectorState.ANOMALY_ACTIVE

    revised = evaluate_instrument(
        policy=policy,
        tracker=tracker,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=2,
        option_book=make_book("SHORT", price),
        ticker=TickerState(Decimal(100), "index_price", 1),
        causal_closes=None,
        baseline_unavailable_reason="INDEX_HISTORY_REVISION",
    )

    assert revised.transition.ended_episode is not None
    assert revised.transition.ended_episode.reason is EpisodeEndReason.UNKNOWN_AT_GAP
    assert revised.transition.ended_episode.detail == "INDEX_HISTORY_REVISION"


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
        instrument.price_tick,
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
        instrument.price_tick,
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
        instrument.price_tick,
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
