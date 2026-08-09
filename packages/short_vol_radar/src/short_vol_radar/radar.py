from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from market_monitor import BookState, ContinuousOrderBook, TimeInterval
from options_domain import (
    LINEAR_BTC_USDC,
    AmountState,
    OptionInstrument,
    OptionType,
    check_target_amount,
    stress_depth_walk_down_one_tick,
)
from options_domain.quotes import DepthWalk, walk_target_depth

from short_vol_radar.baseline import (
    BaselineResult,
    BaselineStatistics,
    BaselineUnavailable,
    compute_baseline,
    project_baseline,
)
from short_vol_radar.black import (
    DecimalInterval,
    NumericalUnknown,
    TotalVolatilityInterval,
    delta_interval,
    executable_iv_interval,
    invert_total_volatility,
    ratio_interval,
)
from short_vol_radar.detector import (
    DetectorObservation,
    DetectorState,
    EpisodeTracker,
    NumericalBoundaryUnresolved,
    TrackerState,
    TrackerTransition,
    classify_observation,
    delta_is_eligible,
)
from short_vol_radar.policy import (
    OptionRule,
    RadarPolicy,
    TimeApplicability,
    TteBand,
    classify_time_applicability,
)

MILLISECONDS_PER_365_DAY_YEAR = Decimal(365 * 24 * 60 * 60 * 1_000)
MILLISECONDS_PER_MINUTE = Decimal(60_000)


@dataclass(frozen=True)
class TickerState:
    forward_usdc: Decimal
    underlying_index: str
    source_timestamp_ms: int
    signed_delta: Decimal | None = None
    mark_iv_fraction: Decimal | None = None


class DeltaBucket(StrEnum):
    EXTREME_TAIL_LT_05 = "EXTREME_TAIL_LT_05"
    TAIL_05_15 = "TAIL_05_15"
    WING_15_30 = "WING_15_30"
    NEAR_ATM_30_40 = "NEAR_ATM_30_40"
    ATM_GT_40 = "ATM_GT_40"


@dataclass(frozen=True)
class DetectorCalculation:
    band: TteBand
    rule: OptionRule
    target_bid: DepthWalk
    target_ask: DepthWalk
    stressed_target_bid: DepthWalk
    price_tick_usdc: Decimal
    target_spread_usdc: Decimal
    target_spread_ticks: Decimal
    bid_premium_ticks: Decimal
    forward_usdc: Decimal
    executable_sell_price_usdc: Decimal
    executable_buy_price_usdc: Decimal
    stressed_executable_sell_price_usdc: Decimal
    baseline: BaselineResult
    remaining_life_years: DecimalInterval
    total_volatility: TotalVolatilityInterval
    stressed_total_volatility: TotalVolatilityInterval
    ask_total_volatility: TotalVolatilityInterval
    executable_bid_iv: DecimalInterval
    stressed_executable_bid_iv: DecimalInterval
    executable_ask_iv: DecimalInterval
    delta: DecimalInterval
    delta_bucket: DeltaBucket
    delta_clue_eligible: bool
    implied_total_variance: DecimalInterval
    raw_richness: DecimalInterval
    richness: DecimalInterval
    product_spec_identity: str = LINEAR_BTC_USDC.identity
    product_name: str = LINEAR_BTC_USDC.name.value
    native_premium_currency: str = LINEAR_BTC_USDC.native_premium_currency
    native_price_tick: Decimal | None = None
    native_target_spread: Decimal | None = None
    native_executable_sell_price: Decimal | None = None
    native_executable_buy_price: Decimal | None = None
    native_stressed_executable_sell_price: Decimal | None = None
    model_conversion_forward: Decimal | None = None

    @property
    def clue_eligible(self) -> bool:
        return self.band.clue_eligible and self.delta_clue_eligible


class CurrentDisposition(StrEnum):
    RICHNESS = "RICHNESS"
    REVIEW_ONLY = "REVIEW_ONLY"
    KNOWN_INELIGIBLE = "KNOWN_INELIGIBLE"
    UNKNOWN = "UNKNOWN"
    BAND_SUSPENDED = "BAND_SUSPENDED"
    OUT_OF_BASELINE_SCOPE = "OUT_OF_BASELINE_SCOPE"


@dataclass(frozen=True)
class CurrentEvaluation:
    disposition: CurrentDisposition
    reason: str | None
    known_evaluation: bool
    full_formula_evaluation: bool
    band_id: str | None
    calculation: DetectorCalculation | None = None
    observation: DetectorObservation | None = None
    continuity_gap: bool = False


@dataclass(frozen=True)
class EvaluationResult:
    detector_state: DetectorState
    reason: str | None
    known_evaluation: bool
    full_formula_evaluation: bool
    band_id: str | None
    transition: TrackerTransition
    observation_eligible: bool = False
    observation_reason: str | None = None
    calculation: DetectorCalculation | None = None
    current_evaluation: CurrentEvaluation | None = None


def detector_observation_identity(
    *,
    policy: RadarPolicy,
    instrument: OptionInstrument,
    trusted_time: TimeInterval,
    option_book: ContinuousOrderBook | None,
    ticker: TickerState | None,
    baseline_identity: tuple[object, ...],
) -> tuple[object, ...]:
    applicability = classify_time_applicability(
        policy,
        expiration_timestamp_ms=instrument.expiration_timestamp_ms,
        trusted_time=trusted_time,
        option_type=instrument.option_type,
    )
    target_bid = None
    target_ask = None
    stressed_bid = None
    if option_book is not None and option_book.state is BookState.USABLE:
        target_bid = walk_target_depth(option_book.levels("bid"), policy.target_base_quantity_btc)
        target_ask = walk_target_depth(option_book.levels("ask"), policy.target_base_quantity_btc)
        if target_bid is not None and instrument.price_tick is not None:
            stressed_bid = stress_depth_walk_down_one_tick(target_bid, instrument.price_tick)
    return (
        applicability.classification.value,
        applicability.band.band_id if applicability.band is not None else None,
        applicability.band.clue_eligible if applicability.band is not None else None,
        tuple(target_bid.consumed) if target_bid is not None else None,
        tuple(target_ask.consumed) if target_ask is not None else None,
        tuple(stressed_bid.consumed) if stressed_bid is not None else None,
        instrument.product.identity,
        instrument.price_tick,
        ticker.forward_usdc if ticker is not None else None,
        baseline_identity,
    )


def evaluate_instrument(
    *,
    policy: RadarPolicy,
    tracker: EpisodeTracker,
    instrument: OptionInstrument,
    trusted_time: TimeInterval,
    causal_seq: int,
    option_book: ContinuousOrderBook | None,
    ticker: TickerState | None,
    causal_closes: tuple[Decimal, ...] | None,
    baseline_unavailable_reason: str = "INDEX_BASELINE_WARMUP",
    observation_eligible: bool = True,
    observation_reason: str | None = None,
) -> EvaluationResult:
    current = calculate_current_evaluation(
        policy=policy,
        instrument=instrument,
        trusted_time=trusted_time,
        causal_seq=causal_seq,
        option_book=option_book,
        ticker=ticker,
        causal_closes=causal_closes,
        baseline_unavailable_reason=baseline_unavailable_reason,
    )
    transition = apply_current_evaluation(
        tracker=tracker,
        current=current,
        causal_seq=causal_seq,
        observation_eligible=observation_eligible,
    )
    return EvaluationResult(
        detector_state=tracker.detector_state,
        reason=current.reason,
        known_evaluation=current.known_evaluation,
        full_formula_evaluation=current.full_formula_evaluation,
        band_id=current.band_id,
        transition=transition,
        observation_eligible=observation_eligible,
        observation_reason=observation_reason,
        calculation=current.calculation,
        current_evaluation=current,
    )


def calculate_current_evaluation(
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
    def current(
        disposition: CurrentDisposition,
        reason: str,
        *,
        known: bool,
        full_formula: bool,
        band_id: str | None,
        calculation: DetectorCalculation | None = None,
        continuity_gap: bool = False,
    ) -> CurrentEvaluation:
        return CurrentEvaluation(
            disposition=disposition,
            reason=reason,
            known_evaluation=known,
            full_formula_evaluation=full_formula,
            band_id=band_id,
            calculation=calculation,
            continuity_gap=continuity_gap,
        )

    if policy.product_spec_identity != instrument.product.identity:
        return current(
            CurrentDisposition.UNKNOWN,
            "PRODUCT_POLICY_MISMATCH",
            known=False,
            full_formula=False,
            band_id=None,
        )

    lower_tte_ms = instrument.expiration_timestamp_ms - trusted_time.upper_ms
    upper_tte_ms = instrument.expiration_timestamp_ms - trusted_time.lower_ms
    applicability = classify_time_applicability(
        policy,
        expiration_timestamp_ms=instrument.expiration_timestamp_ms,
        trusted_time=trusted_time,
        option_type=instrument.option_type,
    )
    if applicability.classification is TimeApplicability.MONITOR_BOUNDARY:
        return current(
            CurrentDisposition.UNKNOWN,
            "TIME_MONITOR_BOUNDARY",
            known=False,
            full_formula=False,
            band_id=None,
        )
    if applicability.classification is TimeApplicability.ADJACENT_BAND_BOUNDARY:
        return current(
            CurrentDisposition.BAND_SUSPENDED,
            "TIME_BAND_BOUNDARY",
            known=False,
            full_formula=False,
            band_id=None,
        )
    band = applicability.band
    if band is None:
        return current(
            CurrentDisposition.OUT_OF_BASELINE_SCOPE,
            "OUT_OF_BASELINE_SCOPE",
            known=False,
            full_formula=False,
            band_id=None,
        )
    rule = band.option_rules[instrument.option_type]

    amount_check = (
        check_target_amount(policy.target_base_quantity_btc, instrument.amount)
        if instrument.amount is not None
        else None
    )
    if amount_check is not None and amount_check.state is AmountState.INELIGIBLE:
        return current(
            CurrentDisposition.KNOWN_INELIGIBLE,
            amount_check.reason or "TARGET_AMOUNT_INELIGIBLE",
            known=True,
            full_formula=False,
            band_id=band.band_id,
        )
    if option_book is None or option_book.state is not BookState.USABLE:
        return current(
            CurrentDisposition.UNKNOWN,
            "OPTION_BOOK_UNKNOWN",
            known=False,
            full_formula=False,
            band_id=band.band_id,
            continuity_gap=(
                option_book is not None and option_book.reason not in {"SNAPSHOT_REQUIRED"}
            ),
        )
    target_bid = walk_target_depth(option_book.levels("bid"), policy.target_base_quantity_btc)
    if target_bid is None:
        return current(
            CurrentDisposition.KNOWN_INELIGIBLE,
            "INSUFFICIENT_TARGET_BID_DEPTH",
            known=True,
            full_formula=False,
            band_id=band.band_id,
        )
    target_ask = walk_target_depth(option_book.levels("ask"), policy.target_base_quantity_btc)
    if target_ask is None:
        return current(
            CurrentDisposition.KNOWN_INELIGIBLE,
            "INSUFFICIENT_TARGET_ASK_DEPTH",
            known=True,
            full_formula=False,
            band_id=band.band_id,
        )
    if target_ask.vwap <= target_bid.vwap:
        return current(
            CurrentDisposition.KNOWN_INELIGIBLE,
            "NON_POSITIVE_TARGET_SPREAD",
            known=True,
            full_formula=False,
            band_id=band.band_id,
        )
    if amount_check is None:
        return current(
            CurrentDisposition.UNKNOWN,
            "OPTION_AMOUNT_METADATA_UNKNOWN",
            known=False,
            full_formula=False,
            band_id=band.band_id,
        )
    if instrument.price_tick is None:
        return current(
            CurrentDisposition.UNKNOWN,
            "OPTION_PRICE_TICK_METADATA_UNKNOWN",
            known=False,
            full_formula=False,
            band_id=band.band_id,
        )
    stressed_target_bid = stress_depth_walk_down_one_tick(target_bid, instrument.price_tick)
    if stressed_target_bid is None:
        return current(
            CurrentDisposition.KNOWN_INELIGIBLE,
            "ONE_TICK_STRESSED_BID_NON_POSITIVE",
            known=True,
            full_formula=False,
            band_id=band.band_id,
        )
    price_tick = instrument.price_tick.tick_size_for_price(target_bid.consumed[0].price)
    if ticker is None:
        return current(
            CurrentDisposition.UNKNOWN,
            ticker_unavailable_reason,
            known=False,
            full_formula=False,
            band_id=band.band_id,
            continuity_gap=ticker_continuity_gap,
        )
    if ticker.forward_usdc <= 0 or not ticker.forward_usdc.is_finite():
        return current(
            CurrentDisposition.UNKNOWN,
            "INVALID_FORWARD",
            known=False,
            full_formula=False,
            band_id=band.band_id,
        )
    if not _is_otm(instrument.option_type, instrument.strike, ticker.forward_usdc):
        return current(
            CurrentDisposition.KNOWN_INELIGIBLE,
            "NOT_OTM",
            known=True,
            full_formula=False,
            band_id=band.band_id,
        )

    product = instrument.product
    model_target_bid = product.model_premium(
        target_bid.vwap,
        forward_price=ticker.forward_usdc,
    )
    model_stressed_target_bid = product.model_premium(
        stressed_target_bid.vwap,
        forward_price=ticker.forward_usdc,
    )
    model_target_ask = product.model_premium(
        target_ask.vwap,
        forward_price=ticker.forward_usdc,
    )

    remaining_years = DecimalInterval(
        Decimal(lower_tte_ms) / MILLISECONDS_PER_365_DAY_YEAR,
        Decimal(upper_tte_ms) / MILLISECONDS_PER_365_DAY_YEAR,
    )
    try:
        total_volatility = invert_total_volatility(
            target_price=model_target_bid,
            forward=ticker.forward_usdc,
            strike=instrument.strike,
            option_type=instrument.option_type,
        )
        stressed_total_volatility = invert_total_volatility(
            target_price=model_stressed_target_bid,
            forward=ticker.forward_usdc,
            strike=instrument.strike,
            option_type=instrument.option_type,
        )
        ask_total_volatility = invert_total_volatility(
            target_price=model_target_ask,
            forward=ticker.forward_usdc,
            strike=instrument.strike,
            option_type=instrument.option_type,
        )
        delta = delta_interval(
            forward=ticker.forward_usdc,
            strike=instrument.strike,
            total_volatility=total_volatility,
            option_type=instrument.option_type,
        )
        delta_clue_eligible = delta_is_eligible(delta, rule)
        delta_bucket = classify_delta_bucket(delta, rule)
        remaining_life_minutes_low = Decimal(lower_tte_ms) / MILLISECONDS_PER_MINUTE
        remaining_life_minutes_high = Decimal(upper_tte_ms) / MILLISECONDS_PER_MINUTE
        if baseline_statistics is None:
            if causal_closes is None:
                raise BaselineUnavailable(baseline_unavailable_reason)
            baseline = compute_baseline(
                sampled_prices=causal_closes,
                lookbacks=band.lookbacks_minutes,
                return_interval_minutes=band.return_interval_minutes,
                annualized_variance_floor=band.annualized_variance_floor,
                remaining_life_minutes_low=remaining_life_minutes_low,
                remaining_life_minutes_high=remaining_life_minutes_high,
            )
        else:
            baseline = project_baseline(
                statistics=baseline_statistics,
                remaining_life_minutes_low=remaining_life_minutes_low,
                remaining_life_minutes_high=remaining_life_minutes_high,
            )
        iv = executable_iv_interval(
            total_volatility=total_volatility,
            time_years=remaining_years,
        )
        stressed_iv = executable_iv_interval(
            total_volatility=stressed_total_volatility,
            time_years=remaining_years,
        )
        ask_iv = executable_iv_interval(
            total_volatility=ask_total_volatility,
            time_years=remaining_years,
        )
        raw_richness = ratio_interval(iv, baseline.annualized_volatility)
        stressed_richness = ratio_interval(stressed_iv, baseline.annualized_volatility)
    except NumericalBoundaryUnresolved:
        return current(
            CurrentDisposition.UNKNOWN,
            "NUMERICAL_BOUNDARY_UNRESOLVED",
            known=False,
            full_formula=False,
            band_id=band.band_id,
        )
    except (NumericalUnknown, BaselineUnavailable) as exc:
        reason = str(exc) or type(exc).__name__
        currentness_gap = reason in {
            "INDEX_BASELINE_STALE",
            "INDEX_BASELINE_GAP",
            "INDEX_WINDOW_GAP",
            "INDEX_SOURCE_STALE",
            "INDEX_CONTINUITY_GAP",
            "INDEX_HISTORY_SOURCE_STALE",
            "INDEX_HISTORY_WINDOW_GAP",
            "INDEX_HISTORY_REVISION",
        }
        return current(
            CurrentDisposition.UNKNOWN,
            reason,
            known=False,
            full_formula=False,
            band_id=band.band_id,
            continuity_gap=currentness_gap,
        )

    implied_total_variance = DecimalInterval(
        total_volatility.lower * total_volatility.lower,
        total_volatility.upper * total_volatility.upper,
    )
    native_spread = target_ask.vwap - target_bid.vwap
    model_price_tick = product.model_premium(
        price_tick,
        forward_price=ticker.forward_usdc,
    )
    model_spread = model_target_ask - model_target_bid
    calculation = DetectorCalculation(
        band=band,
        rule=rule,
        target_bid=target_bid,
        target_ask=target_ask,
        stressed_target_bid=stressed_target_bid,
        price_tick_usdc=model_price_tick,
        target_spread_usdc=model_spread,
        target_spread_ticks=native_spread / price_tick,
        bid_premium_ticks=target_bid.vwap / price_tick,
        forward_usdc=ticker.forward_usdc,
        executable_sell_price_usdc=model_target_bid,
        executable_buy_price_usdc=model_target_ask,
        stressed_executable_sell_price_usdc=model_stressed_target_bid,
        baseline=baseline,
        remaining_life_years=remaining_years,
        total_volatility=total_volatility,
        stressed_total_volatility=stressed_total_volatility,
        ask_total_volatility=ask_total_volatility,
        executable_bid_iv=iv,
        stressed_executable_bid_iv=stressed_iv,
        executable_ask_iv=ask_iv,
        delta=delta,
        delta_bucket=delta_bucket,
        delta_clue_eligible=delta_clue_eligible,
        implied_total_variance=implied_total_variance,
        raw_richness=raw_richness,
        richness=stressed_richness,
        product_spec_identity=product.identity,
        product_name=product.name.value,
        native_premium_currency=product.native_premium_currency,
        native_price_tick=price_tick,
        native_target_spread=native_spread,
        native_executable_sell_price=target_bid.vwap,
        native_executable_buy_price=target_ask.vwap,
        native_stressed_executable_sell_price=stressed_target_bid.vwap,
        model_conversion_forward=ticker.forward_usdc,
    )
    if not calculation.clue_eligible:
        if not band.clue_eligible and not delta_clue_eligible:
            reason = "REVIEW_ONLY_TTE_AND_DELTA"
        elif not band.clue_eligible:
            reason = "REVIEW_ONLY_TTE_BAND"
        else:
            reason = "REVIEW_ONLY_DELTA_BUCKET"
        return current(
            CurrentDisposition.REVIEW_ONLY,
            reason,
            known=True,
            full_formula=True,
            band_id=band.band_id,
            calculation=calculation,
        )
    try:
        signal = classify_observation(stressed_richness, rule)
    except NumericalBoundaryUnresolved:
        return current(
            CurrentDisposition.UNKNOWN,
            "NUMERICAL_BOUNDARY_UNRESOLVED",
            known=False,
            full_formula=False,
            band_id=band.band_id,
        )
    observation = DetectorObservation(
        causal_seq=causal_seq,
        trusted_time=trusted_time,
        band_id=band.band_id,
        signal=signal,
    )
    return CurrentEvaluation(
        disposition=CurrentDisposition.RICHNESS,
        reason=None,
        known_evaluation=True,
        full_formula_evaluation=True,
        band_id=band.band_id,
        calculation=calculation,
        observation=observation,
    )


def classify_delta_bucket(interval: DecimalInterval, rule: OptionRule) -> DeltaBucket:
    absolute_candidates = tuple(abs(value) for value in (interval.lower, interval.upper))
    lower = min(absolute_candidates)
    upper = max(absolute_candidates)
    if upper < rule.abs_delta_min:
        return DeltaBucket.EXTREME_TAIL_LT_05
    if lower > rule.abs_delta_max:
        return DeltaBucket.ATM_GT_40
    midpoint = (lower + upper) / Decimal(2)
    if midpoint <= Decimal("0.15"):
        return DeltaBucket.TAIL_05_15
    if midpoint <= Decimal("0.30"):
        return DeltaBucket.WING_15_30
    return DeltaBucket.NEAR_ATM_30_40


def apply_current_evaluation(
    *,
    tracker: EpisodeTracker,
    current: CurrentEvaluation,
    causal_seq: int,
    observation_eligible: bool,
) -> TrackerTransition:
    if current.disposition is CurrentDisposition.BAND_SUSPENDED:
        return tracker.suspend_for_band_boundary()
    if current.disposition is CurrentDisposition.OUT_OF_BASELINE_SCOPE:
        return tracker.out_of_baseline_scope(causal_seq=causal_seq)

    resumed = tracker.state is TrackerState.BAND_SUSPENDED
    if resumed:
        tracker.resume_after_band_boundary()
    if current.disposition in {
        CurrentDisposition.KNOWN_INELIGIBLE,
        CurrentDisposition.REVIEW_ONLY,
    }:
        return tracker.known_ineligible(
            reason=current.reason or "KNOWN_INELIGIBLE",
            causal_seq=causal_seq,
        )
    if current.disposition is CurrentDisposition.UNKNOWN:
        return tracker.unknown(
            reason=current.reason or "UNKNOWN_DETECTOR",
            causal_seq=causal_seq,
            continuity_gap=current.continuity_gap,
        )
    if current.observation is None or current.calculation is None:
        raise RuntimeError("richness evaluation lacks calculation or observation")
    if not observation_eligible:
        known_current = tracker.establish_known_current()
        return TrackerTransition(state_changed=resumed or known_current.state_changed)
    transition = tracker.observe(current.observation, current.calculation.rule)
    if resumed and not transition.state_changed:
        return TrackerTransition(
            activated_episode_id=transition.activated_episode_id,
            ended_episode=transition.ended_episode,
            state_changed=True,
        )
    return transition


def parse_ticker(payload: object, expected_instrument_name: str) -> TickerState:
    if not isinstance(payload, dict):
        raise ValueError("ticker payload must be an object")
    instrument_name = payload.get("instrument_name")
    timestamp = payload.get("timestamp")
    underlying_price = payload.get("underlying_price")
    underlying_index = payload.get("underlying_index")
    if instrument_name != expected_instrument_name:
        raise ValueError("ticker instrument identity mismatch")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        raise ValueError("ticker timestamp must be a non-negative integer")
    if not isinstance(underlying_index, str) or not underlying_index:
        raise ValueError("ticker underlying_index must be a non-empty string")
    option_name_parts = expected_instrument_name.rsplit("-", 2)
    if len(option_name_parts) != 3:
        raise ValueError("ticker option identity cannot establish its forward basis")
    expected_expiry_future = option_name_parts[0]
    if underlying_index not in {"index_price", expected_expiry_future}:
        raise ValueError("ticker underlying_index is not the expected forward basis")
    try:
        forward = Decimal(str(underlying_price))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("ticker underlying_price must be numeric") from exc
    if not forward.is_finite():
        raise ValueError("ticker underlying_price must be finite")

    greeks = payload.get("greeks")
    raw_delta = greeks.get("delta") if isinstance(greeks, dict) else None
    signed_delta = _parse_optional_finite_decimal(raw_delta)
    if signed_delta is not None and not Decimal("-1") <= signed_delta <= Decimal("1"):
        signed_delta = None

    mark_iv_percent = _parse_optional_finite_decimal(payload.get("mark_iv"))
    mark_iv_fraction = (
        mark_iv_percent / Decimal(100)
        if mark_iv_percent is not None and mark_iv_percent >= 0
        else None
    )
    return TickerState(
        forward,
        underlying_index,
        timestamp,
        signed_delta=signed_delta,
        mark_iv_fraction=mark_iv_fraction,
    )


def _parse_optional_finite_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _is_otm(option_type: OptionType, strike: Decimal, forward: Decimal) -> bool:
    if option_type is OptionType.CALL:
        return strike > forward
    return strike < forward
