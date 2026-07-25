from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from market_monitor import BookState, ContinuousOrderBook, TimeInterval
from options_domain import AmountState, OptionInstrument, OptionType, check_target_amount
from options_domain.quotes import DepthWalk, walk_target_depth

from short_vol_radar.baseline import BaselineResult, BaselineUnavailable, compute_baseline
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


@dataclass(frozen=True)
class DetectorCalculation:
    band: TteBand
    rule: OptionRule
    target_bid: DepthWalk
    forward_usdc: Decimal
    executable_sell_price_usdc: Decimal
    baseline: BaselineResult
    remaining_life_years: DecimalInterval
    total_volatility: TotalVolatilityInterval
    executable_bid_iv: DecimalInterval
    delta: DecimalInterval
    implied_total_variance: DecimalInterval
    richness: DecimalInterval


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
    target_bid = (
        walk_target_depth(option_book.levels("bid"), policy.target_base_quantity_btc)
        if option_book is not None and option_book.state is BookState.USABLE
        else None
    )
    return (
        applicability.classification.value,
        applicability.band.band_id if applicability.band is not None else None,
        tuple(target_bid.consumed) if target_bid is not None else None,
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
    def current_result(
        reason: str,
        *,
        known: bool,
        full_formula: bool,
        band_id: str | None,
        transition: TrackerTransition,
    ) -> EvaluationResult:
        return EvaluationResult(
            detector_state=tracker.detector_state,
            reason=reason,
            known_evaluation=known,
            full_formula_evaluation=full_formula,
            band_id=band_id,
            transition=transition,
            observation_eligible=observation_eligible,
            observation_reason=observation_reason,
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
        transition = tracker.unknown(
            reason="TIME_MONITOR_BOUNDARY",
            causal_seq=causal_seq,
        )
        return current_result(
            "TIME_MONITOR_BOUNDARY",
            known=False,
            full_formula=False,
            band_id=None,
            transition=transition,
        )
    if applicability.classification is TimeApplicability.ADJACENT_BAND_BOUNDARY:
        transition = tracker.suspend_for_band_boundary()
        return current_result(
            "TIME_BAND_BOUNDARY",
            known=False,
            full_formula=False,
            band_id=None,
            transition=transition,
        )
    band = applicability.band
    if band is None:
        transition = tracker.out_of_baseline_scope(causal_seq=causal_seq)
        return current_result(
            "OUT_OF_BASELINE_SCOPE",
            known=False,
            full_formula=False,
            band_id=None,
            transition=transition,
        )
    if tracker.state is TrackerState.BAND_SUSPENDED:
        tracker.resume_after_band_boundary()
    rule = band.option_rules[instrument.option_type]

    amount_check = (
        check_target_amount(policy.target_base_quantity_btc, instrument.amount)
        if instrument.amount is not None
        else None
    )
    if amount_check is not None and amount_check.state is AmountState.INELIGIBLE:
        transition = (
            tracker.known_ineligible(
                reason=amount_check.reason or "TARGET_AMOUNT_INELIGIBLE",
                causal_seq=causal_seq,
            )
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            amount_check.reason or "TARGET_AMOUNT_INELIGIBLE",
            known=True,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    if option_book is None or option_book.state is not BookState.USABLE:
        transition = (
            tracker.unknown(
                reason="OPTION_BOOK_UNKNOWN",
                causal_seq=causal_seq,
                continuity_gap=option_book is not None
                and option_book.reason not in {"SNAPSHOT_REQUIRED"},
            )
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            "OPTION_BOOK_UNKNOWN",
            known=False,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    target_bid = walk_target_depth(option_book.levels("bid"), policy.target_base_quantity_btc)
    if target_bid is None:
        transition = (
            tracker.known_ineligible(
                reason="INSUFFICIENT_TARGET_BID_DEPTH",
                causal_seq=causal_seq,
            )
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            "INSUFFICIENT_TARGET_BID_DEPTH",
            known=True,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    if amount_check is None:
        transition = (
            tracker.unknown(
                reason="OPTION_AMOUNT_METADATA_UNKNOWN",
                causal_seq=causal_seq,
            )
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            "OPTION_AMOUNT_METADATA_UNKNOWN",
            known=False,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    if ticker is None:
        transition = (
            tracker.unknown(
                reason="FORWARD_TICKER_UNKNOWN",
                causal_seq=causal_seq,
            )
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            "FORWARD_TICKER_UNKNOWN",
            known=False,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    if ticker.forward_usdc <= 0 or not ticker.forward_usdc.is_finite():
        transition = (
            tracker.unknown(reason="INVALID_FORWARD", causal_seq=causal_seq)
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            "INVALID_FORWARD",
            known=False,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    if not _is_otm(instrument.option_type, instrument.strike, ticker.forward_usdc):
        transition = (
            tracker.known_ineligible(reason="NOT_OTM", causal_seq=causal_seq)
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            "NOT_OTM",
            known=True,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    remaining_years = DecimalInterval(
        Decimal(lower_tte_ms) / MILLISECONDS_PER_365_DAY_YEAR,
        Decimal(upper_tte_ms) / MILLISECONDS_PER_365_DAY_YEAR,
    )
    try:
        total_volatility = invert_total_volatility(
            target_price=target_bid.vwap,
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
        if not delta_is_eligible(delta, rule):
            transition = (
                tracker.known_ineligible(
                    reason="DELTA_INELIGIBLE",
                    causal_seq=causal_seq,
                )
                if observation_eligible
                else TrackerTransition()
            )
            return current_result(
                "DELTA_INELIGIBLE",
                known=True,
                full_formula=False,
                band_id=band.band_id,
                transition=transition,
            )
        if causal_closes is None:
            raise BaselineUnavailable(baseline_unavailable_reason)
        baseline = compute_baseline(
            closes=causal_closes,
            lookbacks=band.lookbacks_minutes,
            weights=band.lookback_weights,
            annualized_variance_floor=band.annualized_variance_floor,
            remaining_life_minutes_low=Decimal(lower_tte_ms) / MILLISECONDS_PER_MINUTE,
            remaining_life_minutes_high=Decimal(upper_tte_ms) / MILLISECONDS_PER_MINUTE,
        )
        iv = executable_iv_interval(
            total_volatility=total_volatility,
            time_years=remaining_years,
        )
        richness = ratio_interval(iv, baseline.annualized_volatility)
        transition = (
            tracker.observe(
                DetectorObservation(
                    causal_seq=causal_seq,
                    trusted_time=trusted_time,
                    band_id=band.band_id,
                    richness=richness,
                ),
                rule,
            )
            if observation_eligible
            else TrackerTransition()
        )
    except NumericalBoundaryUnresolved:
        transition = (
            tracker.unknown(
                reason="NUMERICAL_BOUNDARY_UNRESOLVED",
                causal_seq=causal_seq,
            )
            if observation_eligible
            else TrackerTransition()
        )
        return current_result(
            "NUMERICAL_BOUNDARY_UNRESOLVED",
            known=False,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    except (NumericalUnknown, BaselineUnavailable) as exc:
        reason = str(exc) or type(exc).__name__
        currentness_gap = reason in {"INDEX_BASELINE_STALE", "INDEX_BASELINE_GAP"}
        transition = (
            tracker.unknown(
                reason=reason,
                causal_seq=causal_seq,
                continuity_gap=currentness_gap,
            )
            if observation_eligible or currentness_gap
            else TrackerTransition()
        )
        return current_result(
            reason,
            known=False,
            full_formula=False,
            band_id=band.band_id,
            transition=transition,
        )
    implied_total_variance = DecimalInterval(
        total_volatility.lower * total_volatility.lower,
        total_volatility.upper * total_volatility.upper,
    )
    calculation = DetectorCalculation(
        band=band,
        rule=rule,
        target_bid=target_bid,
        forward_usdc=ticker.forward_usdc,
        executable_sell_price_usdc=target_bid.vwap,
        baseline=baseline,
        remaining_life_years=remaining_years,
        total_volatility=total_volatility,
        executable_bid_iv=iv,
        delta=delta,
        implied_total_variance=implied_total_variance,
        richness=richness,
    )
    return EvaluationResult(
        detector_state=tracker.detector_state,
        reason=None,
        known_evaluation=True,
        full_formula_evaluation=True,
        band_id=band.band_id,
        transition=transition,
        observation_eligible=observation_eligible,
        observation_reason=observation_reason,
        calculation=calculation,
    )


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
    except Exception as exc:
        raise ValueError("ticker underlying_price must be numeric") from exc
    if not forward.is_finite():
        raise ValueError("ticker underlying_price must be finite")
    return TickerState(forward, underlying_index, timestamp)


def _is_otm(option_type: OptionType, strike: Decimal, forward: Decimal) -> bool:
    if option_type is OptionType.CALL:
        return strike > forward
    return strike < forward
