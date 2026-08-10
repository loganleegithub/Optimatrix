from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from market_monitor import ContinuousOrderBook, PriceLevel
from options_domain import (
    INVERSE_BTC,
    AmountMetadata,
    DepthWalk,
    OptionInstrument,
    OptionType,
    PriceTickMetadata,
    standard_option_fee_native,
)
from short_vol_radar.baseline import BaselineResult, WindowDiagnostics
from short_vol_radar.black import DecimalInterval, TotalVolatilityInterval
from short_vol_radar.detector import DetectorState
from short_vol_radar.policy import OptionRule, TteBand
from short_vol_radar.radar import DeltaBucket, DetectorCalculation, TickerState
from short_vol_radar.review import (
    LEGGED_REFERENCE_NON_CLAIMS,
    DiagnosticState,
    LeggedReferenceState,
    build_review_contexts,
    build_score_feature_contexts,
)

TARGET_QUANTITY = Decimal("0.1")
FEE_RATE = Decimal("0.0003")
EXPIRY_MS = 86_400_000
AMOUNT = AmountMetadata(Decimal(1), TARGET_QUANTITY, TARGET_QUANTITY)
PRICE_TICK = PriceTickMetadata(Decimal("0.000001"))


def _option(
    name: str,
    strike: str,
    option_type: OptionType,
    *,
    expiry_ms: int = EXPIRY_MS,
) -> OptionInstrument:
    return OptionInstrument(
        instrument_name=name,
        expiration_timestamp_ms=expiry_ms,
        strike=Decimal(strike),
        option_type=option_type,
        amount=AMOUNT,
        price_tick=PRICE_TICK,
    )


def _walk(price: str) -> DepthWalk:
    parsed = Decimal(price) / Decimal("100000")
    return DepthWalk(
        consumed=(PriceLevel(parsed, TARGET_QUANTITY),),
        target_amount=TARGET_QUANTITY,
        total_value=parsed * TARGET_QUANTITY,
        vwap=parsed,
    )


def _book(name: str, *, bid: str, ask: str) -> ContinuousOrderBook:
    native_bid = Decimal(bid) / Decimal("100000")
    native_ask = Decimal(ask) / Decimal("100000")
    book = ContinuousOrderBook(name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": name,
            "change_id": 1,
            "bids": [["new", native_bid, str(TARGET_QUANTITY)]],
            "asks": [["new", native_ask, str(TARGET_QUANTITY)]],
        },
        1,
    )
    return book


def _baseline() -> BaselineResult:
    diagnostics = WindowDiagnostics(
        lookback_minutes=120,
        return_count=24,
        variance_rate_per_minute=Decimal("0.000001"),
        positive_semivariance_rate_per_minute=Decimal("0.0000007"),
        negative_semivariance_rate_per_minute=Decimal("0.0000003"),
        positive_semivariance_share=Decimal("0.7"),
        negative_semivariance_share=Decimal("0.3"),
        bipower_variation_rate_per_minute=Decimal("0.0000008"),
        jump_variation_rate_per_minute=Decimal("0.0000002"),
        jump_share=Decimal("0.2"),
        maximum_absolute_return=Decimal("0.03"),
        net_return=Decimal("0.01"),
    )
    return BaselineResult(
        return_interval_minutes=5,
        window_variances=((120, Decimal("0.000001")),),
        selected_lookback_minutes=120,
        variance_rate_per_minute=Decimal("0.000001"),
        annualized_volatility=Decimal("0.50"),
        total_variance_low=Decimal("0.0001"),
        total_variance_high=Decimal("0.0002"),
        window_diagnostics=(diagnostics,),
    )


def _calculation(
    option_type: OptionType,
    *,
    delta_lower: str,
    delta_upper: str,
    richness_lower: str = "1.38",
    clue_eligible_tte: bool = True,
    clue_eligible_delta: bool = True,
) -> DetectorCalculation:
    rule = OptionRule(
        abs_delta_min=Decimal("0.05"),
        abs_delta_max=Decimal("0.40"),
        activation_observation_count=3,
        clear_observation_count=2,
        minimum_separation_ms=300_000,
    )
    band = TteBand(
        band_id="INTRADAY",
        lower_bound_minutes=360,
        upper_bound_minutes=1_440,
        clue_eligible=clue_eligible_tte,
        return_interval_minutes=5,
        lookbacks_minutes=(30, 120, 360),
        annualized_variance_floor=Decimal("0.01"),
        option_rules={OptionType.CALL: rule, OptionType.PUT: rule},
    )
    delta = DecimalInterval(Decimal(delta_lower), Decimal(delta_upper))
    abs_midpoint = (abs(delta.lower) + abs(delta.upper)) / Decimal(2)
    if abs_midpoint < Decimal("0.05"):
        delta_bucket = DeltaBucket.EXTREME_TAIL_LT_05
    elif abs_midpoint < Decimal("0.15"):
        delta_bucket = DeltaBucket.TAIL_05_15
    elif abs_midpoint < Decimal("0.30"):
        delta_bucket = DeltaBucket.WING_15_30
    elif abs_midpoint <= Decimal("0.40"):
        delta_bucket = DeltaBucket.NEAR_ATM_30_40
    else:
        delta_bucket = DeltaBucket.ATM_GT_40
    return DetectorCalculation(
        band=band,
        rule=rule,
        target_bid=_walk("12"),
        target_ask=_walk("13"),
        stressed_target_bid=_walk("11.9"),
        price_tick_usdc=Decimal("0.1"),
        target_spread_usdc=Decimal(1),
        target_spread_ticks=Decimal(10),
        bid_premium_ticks=Decimal(120),
        forward_usdc=Decimal(100),
        executable_sell_price_usdc=Decimal(12),
        executable_buy_price_usdc=Decimal(13),
        stressed_executable_sell_price_usdc=Decimal("11.9"),
        baseline=_baseline(),
        remaining_life_years=DecimalInterval(Decimal("0.001"), Decimal("0.0011")),
        total_volatility=TotalVolatilityInterval(Decimal("0.02"), Decimal("0.021")),
        stressed_total_volatility=TotalVolatilityInterval(Decimal("0.019"), Decimal("0.020")),
        ask_total_volatility=TotalVolatilityInterval(Decimal("0.022"), Decimal("0.023")),
        executable_bid_iv=DecimalInterval(Decimal("0.70"), Decimal("0.72")),
        stressed_executable_bid_iv=DecimalInterval(Decimal("0.69"), Decimal("0.71")),
        executable_ask_iv=DecimalInterval(Decimal("0.74"), Decimal("0.76")),
        delta=delta,
        delta_bucket=delta_bucket,
        delta_clue_eligible=clue_eligible_delta,
        implied_total_variance=DecimalInterval(Decimal("0.0004"), Decimal("0.000441")),
        raw_richness=DecimalInterval(Decimal("1.40"), Decimal("1.44")),
        richness=DecimalInterval(
            Decimal(richness_lower), Decimal(richness_lower) + Decimal("0.04")
        ),
    )


def _ticker(delta: str, mark_iv: str) -> TickerState:
    return TickerState(
        forward_usdc=Decimal(100),
        underlying_index="index_price",
        source_timestamp_ms=1,
        signed_delta=Decimal(delta),
        mark_iv_fraction=Decimal(mark_iv),
    )


def test_inverse_standard_option_fee_uses_native_rate_and_premium_cap() -> None:
    capped = standard_option_fee_native(
        product=INVERSE_BTC,
        index_price=Decimal("100000"),
        native_option_price=Decimal("0.00002"),
        quantity_btc=TARGET_QUANTITY,
        fee_rate=FEE_RATE,
    )
    rate_limited = standard_option_fee_native(
        product=INVERSE_BTC,
        index_price=Decimal("100000"),
        native_option_price=Decimal("0.01"),
        quantity_btc=TARGET_QUANTITY,
        fee_rate=FEE_RATE,
    )

    assert capped == Decimal("0.000000250")
    assert rate_limited == Decimal("0.000030")


def test_review_builds_regime_surface_and_non_atomic_vertical_reference() -> None:
    candidate = _option("C100", "100", OptionType.CALL)
    lower_delta = _option("C110", "110", OptionType.CALL)
    upper_delta = _option("C95", "95", OptionType.CALL)
    atm = _option("C90", "90", OptionType.CALL)
    put_25 = _option("P80", "80", OptionType.PUT)
    adjacent = _option(
        "C2ATM",
        "90",
        OptionType.CALL,
        expiry_ms=EXPIRY_MS + 86_400_000,
    )
    options = {
        member.instrument_name: member
        for member in (candidate, lower_delta, upper_delta, atm, put_25, adjacent)
    }
    calculations = {
        candidate.instrument_name: _calculation(
            OptionType.CALL,
            delta_lower="0.24",
            delta_upper="0.26",
        )
    }
    tickers = {
        "C100": _ticker("0.25", "0.60"),
        "C110": _ticker("0.15", "0.65"),
        "C95": _ticker("0.35", "0.58"),
        "C90": _ticker("0.50", "0.55"),
        "P80": _ticker("-0.25", "0.68"),
        "C2ATM": _ticker("0.50", "0.56"),
    }
    contexts = build_review_contexts(
        options=options,
        calculations=calculations,
        detector_states={"C100": DetectorState.ANOMALY_ACTIVE},
        detector_reasons={"C100": None},
        tickers=tickers,
        option_books={
            "C100": _book("C100", bid="12", ask="13"),
            "C110": _book("C110", bid="2.8", ask="3.0"),
        },
        option_catalog_complete=True,
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=TARGET_QUANTITY,
        fee_rate_index_fraction=FEE_RATE,
        attention_top_n=1,
    )

    review = contexts["C100"]
    assert review.hard_screen_label == "V2_SCORE_EPISODE_ACTIVE"
    assert review.regime.state is DiagnosticState.AVAILABLE
    assert review.regime.adverse_semivariance_share == Decimal("0.7")
    assert review.surface.state is DiagnosticState.AVAILABLE
    assert review.surface.twenty_five_delta_risk_reversal == Decimal("-0.08")
    assert review.surface.local_interpolated_mark_iv == Decimal("0.615")
    assert review.surface.stressed_executable_bid_iv_minus_local_mark_iv == Decimal("0.085")
    assert review.surface.current_minus_adjacent_expiry_atm_iv == Decimal("-0.01")
    assert review.legged_structure.state is LeggedReferenceState.LEGGED_REFERENCE_NOT_ATOMIC
    assert review.legged_structure.as_object()["non_claims"] == list(LEGGED_REFERENCE_NON_CLAIMS)
    (reference,) = review.legged_structure.references
    assert reference.long_instrument_name == "C110"
    assert reference.stressed_gross_credit_usdc == Decimal("0.88")
    assert reference.total_fee_reserve_usdc == Decimal("0.18750")
    assert reference.stressed_net_credit_usdc == Decimal("0.69250")
    assert reference.payoff_cap_usdc == Decimal("1.0")
    assert reference.credit_to_payoff_cap_fraction == Decimal("0.6925")
    assert review.attention_rank == 1
    assert review.within_attention_top_n is True


def test_put_surface_uses_absolute_delta_and_negative_semivariance_as_adverse() -> None:
    candidate = _option("P100", "100", OptionType.PUT)
    lower_delta = _option("P90", "90", OptionType.PUT)
    upper_delta = _option("P105", "105", OptionType.PUT)
    call_25 = _option("C120", "120", OptionType.CALL)
    options = {
        member.instrument_name: member for member in (candidate, lower_delta, upper_delta, call_25)
    }
    contexts = build_review_contexts(
        options=options,
        calculations={
            "P100": _calculation(
                OptionType.PUT,
                delta_lower="-0.26",
                delta_upper="-0.24",
            )
        },
        detector_states={"P100": DetectorState.NO_ANOMALY},
        tickers={
            "P100": _ticker("-0.25", "0.66"),
            "P90": _ticker("-0.15", "0.70"),
            "P105": _ticker("-0.35", "0.60"),
            "C120": _ticker("0.25", "0.58"),
        },
        option_books={},
        option_catalog_complete=False,
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=TARGET_QUANTITY,
        fee_rate_index_fraction=FEE_RATE,
    )

    review = contexts["P100"]
    assert review.regime.adverse_semivariance_share == Decimal("0.3")
    assert review.surface.local_lower_instrument_name == "P90"
    assert review.surface.local_upper_instrument_name == "P105"
    assert review.surface.local_interpolated_mark_iv == Decimal("0.65")
    assert review.rank_inputs.abs_delta_midpoint == Decimal("0.25")


def test_term_feature_uses_immediate_next_longer_expiry_not_closer_previous_expiry() -> None:
    current = _option("CURRENT", "100", OptionType.CALL)
    previous = _option(
        "PREVIOUS",
        "100",
        OptionType.CALL,
        expiry_ms=EXPIRY_MS - 3_600_000,
    )
    next_longer = _option(
        "NEXT",
        "100",
        OptionType.CALL,
        expiry_ms=EXPIRY_MS + 7_200_000,
    )
    later = _option(
        "LATER",
        "100",
        OptionType.CALL,
        expiry_ms=EXPIRY_MS + 10_800_000,
    )
    contexts = build_score_feature_contexts(
        options={
            option.instrument_name: option for option in (current, previous, next_longer, later)
        },
        calculations={
            current.instrument_name: _calculation(
                OptionType.CALL,
                delta_lower="0.24",
                delta_upper="0.26",
            )
        },
        tickers={
            "CURRENT": _ticker("0.50", "0.60"),
            "PREVIOUS": _ticker("0.50", "0.54"),
            "NEXT": _ticker("0.50", "0.57"),
            "LATER": _ticker("0.50", "0.56"),
        },
    )

    surface = contexts[current.instrument_name].surface
    assert surface.adjacent_expiry_timestamp_ms == next_longer.expiration_timestamp_ms
    assert surface.adjacent_expiry_atm_instrument_name == next_longer.instrument_name
    assert surface.current_minus_adjacent_expiry_atm_iv == Decimal("0.03")


def test_term_feature_is_unknown_without_a_next_longer_expiry() -> None:
    current = _option("CURRENT", "100", OptionType.CALL)
    previous = _option(
        "PREVIOUS",
        "100",
        OptionType.CALL,
        expiry_ms=EXPIRY_MS - 3_600_000,
    )
    contexts = build_score_feature_contexts(
        options={current.instrument_name: current, previous.instrument_name: previous},
        calculations={
            current.instrument_name: _calculation(
                OptionType.CALL,
                delta_lower="0.24",
                delta_upper="0.26",
            )
        },
        tickers={
            "CURRENT": _ticker("0.50", "0.60"),
            "PREVIOUS": _ticker("0.50", "0.54"),
        },
    )

    surface = contexts[current.instrument_name].surface
    assert surface.adjacent_expiry_timestamp_ms is None
    assert surface.adjacent_expiry_atm_mark_iv is None
    assert surface.current_minus_adjacent_expiry_atm_iv is None


def test_review_only_delta_keeps_tte_eligible_and_active_witness_ranks_first() -> None:
    active = _option("ACTIVE", "100", OptionType.CALL)
    richer_but_inactive = _option("INACTIVE", "101", OptionType.CALL)
    delta_review = _option("DELTA-REVIEW", "102", OptionType.CALL)
    options = {
        member.instrument_name: member for member in (active, richer_but_inactive, delta_review)
    }
    calculations = {
        "ACTIVE": _calculation(
            OptionType.CALL,
            delta_lower="0.20",
            delta_upper="0.22",
            richness_lower="1.25",
        ),
        "INACTIVE": _calculation(
            OptionType.CALL,
            delta_lower="0.20",
            delta_upper="0.22",
            richness_lower="1.40",
        ),
        "DELTA-REVIEW": _calculation(
            OptionType.CALL,
            delta_lower="0.02",
            delta_upper="0.03",
            richness_lower="1.50",
            clue_eligible_delta=False,
        ),
    }
    contexts = build_review_contexts(
        options=options,
        calculations=calculations,
        detector_states={
            "ACTIVE": DetectorState.ANOMALY_ACTIVE,
            "INACTIVE": DetectorState.NO_ANOMALY,
            "DELTA-REVIEW": DetectorState.NO_ANOMALY,
        },
        detector_reasons={"DELTA-REVIEW": "REVIEW_ONLY_DELTA_BUCKET"},
        tickers={},
        option_books={},
        option_catalog_complete=True,
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=TARGET_QUANTITY,
        fee_rate_index_fraction=FEE_RATE,
        attention_top_n=1,
    )

    assert contexts["ACTIVE"].attention_rank == 1
    assert contexts["ACTIVE"].within_attention_top_n is True
    delta_context = contexts["DELTA-REVIEW"]
    assert delta_context.hard_screen_label == "REVIEW_ONLY_DELTA"
    assert delta_context.rank_inputs.clue_eligible_tte is True
    assert delta_context.rank_inputs.clue_eligible_delta is False
    assert delta_context.rank_inputs.clue_eligible is False


def test_rank_is_deterministic_for_identical_economic_inputs() -> None:
    first = _option("A", "100", OptionType.CALL)
    second = _option("B", "100", OptionType.CALL)
    calculation = _calculation(
        OptionType.CALL,
        delta_lower="0.20",
        delta_upper="0.22",
    )
    contexts = build_review_contexts(
        options={"B": second, "A": first},
        calculations={"A": calculation, "B": replace(calculation)},
        detector_states={"A": DetectorState.NO_ANOMALY, "B": DetectorState.NO_ANOMALY},
        tickers={},
        option_books={},
        option_catalog_complete=True,
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=TARGET_QUANTITY,
        fee_rate_index_fraction=FEE_RATE,
    )

    assert contexts["A"].attention_rank == 1
    assert contexts["B"].attention_rank == 2
