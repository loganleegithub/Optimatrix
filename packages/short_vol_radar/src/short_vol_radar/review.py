from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from market_monitor import BookState, ContinuousOrderBook
from options_domain import (
    ComponentBookQuoteKind,
    InstrumentLifecycleState,
    OptionInstrument,
    OptionType,
    evaluate_component_book_vertical,
)

from short_vol_radar.detector import DetectorState
from short_vol_radar.radar import DetectorCalculation, TickerState, radar_score_inputs
from short_vol_radar.score import RadarScoreInputs

DEFAULT_ATTENTION_TOP_N = 20
FIVE_DELTA_POINTS = Decimal("0.05")
TARGET_TWENTY_FIVE_DELTA = Decimal("0.25")
TARGET_ATM_DELTA = Decimal("0.50")
_LARGE_RANK_VALUE = Decimal("1e100")

LEGGED_REFERENCE_NON_CLAIMS = (
    "NOT_AN_ORDER",
    "NOT_A_FILL",
    "NOT_AN_ATOMIC_QUOTE",
    "NO_LIQUIDITY_RESERVATION",
    "CANDIDATE_REQUIRES_STRICTLY_LATER_PAIRED_REFRESH",
)


class DiagnosticState(StrEnum):
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    AVAILABLE = "AVAILABLE"


class LeggedReferenceState(StrEnum):
    UNKNOWN = "UNKNOWN"
    NO_PROTECTIVE_LEG = "NO_PROTECTIVE_LEG"
    NO_TARGET_SIZE_REFERENCE = "NO_TARGET_SIZE_REFERENCE"
    LEGGED_REFERENCE_NOT_ATOMIC = "LEGGED_REFERENCE_NOT_ATOMIC"


@dataclass(frozen=True)
class RegimeContext:
    state: DiagnosticState
    lookback_minutes: int | None = None
    positive_semivariance_share: Decimal | None = None
    negative_semivariance_share: Decimal | None = None
    adverse_semivariance_share: Decimal | None = None
    jump_share: Decimal | None = None
    maximum_absolute_return: Decimal | None = None
    net_return: Decimal | None = None

    def as_object(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "lookback_minutes": self.lookback_minutes,
            "positive_semivariance_share": _decimal_text(self.positive_semivariance_share),
            "negative_semivariance_share": _decimal_text(self.negative_semivariance_share),
            "adverse_semivariance_share": _decimal_text(self.adverse_semivariance_share),
            "jump_share": _decimal_text(self.jump_share),
            "maximum_absolute_return": _decimal_text(self.maximum_absolute_return),
            "net_return": _decimal_text(self.net_return),
            "non_claims": [
                "DESCRIPTIVE_FINITE_SAMPLE_CONTEXT",
                "NOT_A_DELIVERY_PERIOD_FORECAST",
                "NOT_A_DETECTOR_GATE",
            ],
        }


@dataclass(frozen=True)
class SurfaceContext:
    state: DiagnosticState
    same_expiry_atm_instrument_name: str | None = None
    same_expiry_atm_abs_delta: Decimal | None = None
    same_expiry_atm_mark_iv: Decimal | None = None
    nearest_25d_call_instrument_name: str | None = None
    nearest_25d_call_abs_delta: Decimal | None = None
    nearest_25d_call_mark_iv: Decimal | None = None
    nearest_25d_put_instrument_name: str | None = None
    nearest_25d_put_abs_delta: Decimal | None = None
    nearest_25d_put_mark_iv: Decimal | None = None
    twenty_five_delta_risk_reversal: Decimal | None = None
    local_lower_instrument_name: str | None = None
    local_lower_abs_delta: Decimal | None = None
    local_lower_mark_iv: Decimal | None = None
    local_upper_instrument_name: str | None = None
    local_upper_abs_delta: Decimal | None = None
    local_upper_mark_iv: Decimal | None = None
    local_interpolated_mark_iv: Decimal | None = None
    stressed_executable_bid_iv_midpoint: Decimal | None = None
    stressed_executable_bid_iv_minus_local_mark_iv: Decimal | None = None
    adjacent_expiry_timestamp_ms: int | None = None
    adjacent_expiry_atm_instrument_name: str | None = None
    adjacent_expiry_atm_mark_iv: Decimal | None = None
    current_minus_adjacent_expiry_atm_iv: Decimal | None = None

    def as_object(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "same_expiry_atm": {
                "instrument_name": self.same_expiry_atm_instrument_name,
                "abs_delta": _decimal_text(self.same_expiry_atm_abs_delta),
                "mark_iv": _decimal_text(self.same_expiry_atm_mark_iv),
            },
            "nearest_25d_call": {
                "instrument_name": self.nearest_25d_call_instrument_name,
                "abs_delta": _decimal_text(self.nearest_25d_call_abs_delta),
                "mark_iv": _decimal_text(self.nearest_25d_call_mark_iv),
            },
            "nearest_25d_put": {
                "instrument_name": self.nearest_25d_put_instrument_name,
                "abs_delta": _decimal_text(self.nearest_25d_put_abs_delta),
                "mark_iv": _decimal_text(self.nearest_25d_put_mark_iv),
            },
            "twenty_five_delta_risk_reversal": _decimal_text(self.twenty_five_delta_risk_reversal),
            "local_same_type_interpolation": {
                "lower_instrument_name": self.local_lower_instrument_name,
                "lower_abs_delta": _decimal_text(self.local_lower_abs_delta),
                "lower_mark_iv": _decimal_text(self.local_lower_mark_iv),
                "upper_instrument_name": self.local_upper_instrument_name,
                "upper_abs_delta": _decimal_text(self.local_upper_abs_delta),
                "upper_mark_iv": _decimal_text(self.local_upper_mark_iv),
                "interpolated_mark_iv": _decimal_text(self.local_interpolated_mark_iv),
            },
            "stressed_executable_bid_iv_midpoint": _decimal_text(
                self.stressed_executable_bid_iv_midpoint
            ),
            "stressed_executable_bid_iv_minus_local_mark_iv": _decimal_text(
                self.stressed_executable_bid_iv_minus_local_mark_iv
            ),
            "adjacent_expiry_atm": {
                "expiration_timestamp_ms": self.adjacent_expiry_timestamp_ms,
                "instrument_name": self.adjacent_expiry_atm_instrument_name,
                "mark_iv": _decimal_text(self.adjacent_expiry_atm_mark_iv),
                "current_minus_adjacent_iv": _decimal_text(
                    self.current_minus_adjacent_expiry_atm_iv
                ),
            },
            "non_claims": [
                "MARK_IV_DIAGNOSTIC_ONLY",
                "NO_FITTED_SURFACE",
                "NOT_A_DETECTOR_GATE",
                "NOT_A_MISPRICING_CLAIM",
            ],
        }


@dataclass(frozen=True)
class LeggedVerticalReference:
    long_instrument_name: str
    product_spec_identity: str
    product_name: str
    native_premium_currency: str
    valuation_currency: str
    strike_currency: str
    valuation_index_price: Decimal
    short_strike_usdc_per_btc: Decimal
    long_strike_usdc_per_btc: Decimal
    raw_short_bid_vwap_usdc_per_btc: Decimal
    stressed_short_bid_vwap_usdc_per_btc: Decimal
    raw_long_ask_vwap_usdc_per_btc: Decimal
    stressed_long_ask_vwap_usdc_per_btc: Decimal
    stressed_gross_credit_usdc: Decimal
    short_fee_reserve_usdc: Decimal
    long_fee_reserve_usdc: Decimal
    total_fee_reserve_usdc: Decimal
    stressed_net_credit_usdc: Decimal
    stressed_gross_credit_native: Decimal
    short_fee_reserve_native: Decimal
    long_fee_reserve_native: Decimal
    total_fee_reserve_native: Decimal
    stressed_net_credit_native: Decimal
    width_usdc_per_btc: Decimal
    payoff_cap_usdc: Decimal
    maximum_loss_after_fee_reserve_usdc: Decimal
    credit_to_payoff_cap_fraction: Decimal

    def as_object(self) -> dict[str, object]:
        return {
            "long_instrument_name": self.long_instrument_name,
            "product_spec_identity": self.product_spec_identity,
            "product_name": self.product_name,
            "native_premium_currency": self.native_premium_currency,
            "valuation_currency": self.valuation_currency,
            "strike_currency": self.strike_currency,
            "valuation_index_price": str(self.valuation_index_price),
            "short_strike_price": str(self.short_strike_usdc_per_btc),
            "long_strike_price": str(self.long_strike_usdc_per_btc),
            "raw_short_bid_vwap_native": str(self.raw_short_bid_vwap_usdc_per_btc),
            "stressed_short_bid_vwap_native": str(self.stressed_short_bid_vwap_usdc_per_btc),
            "raw_long_ask_vwap_native": str(self.raw_long_ask_vwap_usdc_per_btc),
            "stressed_long_ask_vwap_native": str(self.stressed_long_ask_vwap_usdc_per_btc),
            "stressed_gross_credit_native": str(self.stressed_gross_credit_native),
            "short_fee_reserve_native": str(self.short_fee_reserve_native),
            "long_fee_reserve_native": str(self.long_fee_reserve_native),
            "total_fee_reserve_native": str(self.total_fee_reserve_native),
            "stressed_net_credit_native": str(self.stressed_net_credit_native),
            "stressed_gross_credit_valuation": str(self.stressed_gross_credit_usdc),
            "short_fee_reserve_valuation": str(self.short_fee_reserve_usdc),
            "long_fee_reserve_valuation": str(self.long_fee_reserve_usdc),
            "total_fee_reserve_valuation": str(self.total_fee_reserve_usdc),
            "stressed_net_credit_valuation": str(self.stressed_net_credit_usdc),
            "width_strike_currency_per_btc": str(self.width_usdc_per_btc),
            "contractual_payoff_cap_strike_currency": str(self.payoff_cap_usdc),
            "entry_boundary_valued_payoff_loss_including_fee_valuation": str(
                self.maximum_loss_after_fee_reserve_usdc
            ),
            "credit_to_payoff_cap_fraction": str(self.credit_to_payoff_cap_fraction),
        }


@dataclass(frozen=True)
class LeggedStructureContext:
    state: LeggedReferenceState
    references: tuple[LeggedVerticalReference, ...] = ()
    missing_reasons: tuple[str, ...] = ()

    @property
    def best_credit_to_payoff_cap_fraction(self) -> Decimal | None:
        return self.references[0].credit_to_payoff_cap_fraction if self.references else None

    def as_object(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "references": [reference.as_object() for reference in self.references],
            "best_credit_to_payoff_cap_fraction": _decimal_text(
                self.best_credit_to_payoff_cap_fraction
            ),
            "missing_reasons": list(self.missing_reasons),
            "non_claims": list(LEGGED_REFERENCE_NON_CLAIMS),
        }


@dataclass(frozen=True)
class RankInputs:
    detector_state: DetectorState
    formula_available: bool
    clue_eligible_tte: bool
    clue_eligible_delta: bool
    stressed_richness_lower: Decimal | None
    surface_residual: Decimal | None
    best_legged_credit_to_payoff_cap_fraction: Decimal | None
    adverse_semivariance_share: Decimal | None
    jump_share: Decimal | None
    target_spread_ticks: Decimal | None
    consumed_level_count: int | None
    expiration_timestamp_ms: int
    option_type: OptionType
    abs_delta_midpoint: Decimal | None
    strike_usdc_per_btc: Decimal
    instrument_name: str

    @property
    def clue_eligible(self) -> bool:
        return self.clue_eligible_tte and self.clue_eligible_delta

    def as_object(self) -> dict[str, object]:
        return {
            "detector_state": self.detector_state.value,
            "formula_available": self.formula_available,
            "clue_eligible_tte": self.clue_eligible_tte,
            "clue_eligible_delta": self.clue_eligible_delta,
            "stressed_richness_lower": _decimal_text(self.stressed_richness_lower),
            "surface_residual": _decimal_text(self.surface_residual),
            "best_legged_credit_to_payoff_cap_fraction": _decimal_text(
                self.best_legged_credit_to_payoff_cap_fraction
            ),
            "adverse_semivariance_share": _decimal_text(self.adverse_semivariance_share),
            "jump_share": _decimal_text(self.jump_share),
            "target_spread_ticks": _decimal_text(self.target_spread_ticks),
            "consumed_level_count": self.consumed_level_count,
            "expiration_timestamp_ms": self.expiration_timestamp_ms,
            "option_type": self.option_type.value,
            "abs_delta_midpoint": _decimal_text(self.abs_delta_midpoint),
            "strike_price": str(self.strike_usdc_per_btc),
            "instrument_name": self.instrument_name,
        }


@dataclass(frozen=True)
class ReviewContext:
    hard_screen_label: str
    positive_witness: str
    primary_blocker: str
    upgrade_condition: str
    invalidation_condition: str
    regime: RegimeContext
    surface: SurfaceContext
    legged_structure: LeggedStructureContext
    rank_inputs: RankInputs
    attention_rank: int = 0
    within_attention_top_n: bool = False
    rank_explanation: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreFeatureContext:
    option_type: OptionType
    regime: RegimeContext
    surface: SurfaceContext

    def score_inputs(self, calculation: DetectorCalculation) -> RadarScoreInputs:
        return radar_score_inputs(
            self.option_type,
            calculation,
            local_same_type_mark_iv=self.surface.local_interpolated_mark_iv,
            current_expiry_atm_mark_iv=self.surface.same_expiry_atm_mark_iv,
            adjacent_expiry_atm_mark_iv=self.surface.adjacent_expiry_atm_mark_iv,
        )


@dataclass(frozen=True)
class _SurfacePoint:
    instrument_name: str
    expiration_timestamp_ms: int
    option_type: OptionType
    abs_delta: Decimal
    mark_iv: Decimal


@dataclass(frozen=True)
class _HardScreenExplanation:
    label: str
    positive_witness: str
    blocker: str
    upgrade_condition: str
    invalidation_condition: str


def build_review_contexts(
    *,
    options: Mapping[str, OptionInstrument],
    calculations: Mapping[str, DetectorCalculation],
    detector_states: Mapping[str, DetectorState],
    detector_reasons: Mapping[str, str | None] | None = None,
    tickers: Mapping[str, TickerState],
    option_books: Mapping[str, ContinuousOrderBook],
    option_catalog_complete: bool,
    index_usdc_per_btc: Decimal | None,
    target_quantity_btc: Decimal,
    fee_rate_index_fraction: Decimal,
    attention_top_n: int = DEFAULT_ATTENTION_TOP_N,
) -> dict[str, ReviewContext]:
    if isinstance(attention_top_n, bool) or attention_top_n <= 0:
        raise ValueError("attention_top_n must be a positive integer")
    if not target_quantity_btc.is_finite() or target_quantity_btc <= 0:
        raise ValueError("target_quantity_btc must be finite and positive")
    reasons = detector_reasons or {}
    score_contexts = build_score_feature_contexts(
        options=options,
        calculations=calculations,
        tickers=tickers,
    )
    unranked: dict[str, ReviewContext] = {}
    for instrument_name, instrument in options.items():
        calculation = calculations.get(instrument_name)
        detector_state = detector_states.get(instrument_name, DetectorState.UNKNOWN)
        score_context = score_contexts[instrument_name]
        regime = score_context.regime
        surface = score_context.surface
        legged = _legged_structure_context(
            short_instrument=instrument,
            calculation=calculation,
            options=options,
            option_books=option_books,
            option_catalog_complete=option_catalog_complete,
            index_usdc_per_btc=index_usdc_per_btc,
            target_quantity_btc=target_quantity_btc,
            fee_rate_index_fraction=fee_rate_index_fraction,
        )
        explanation = _hard_screen_explanation(
            detector_state=detector_state,
            detector_reason=reasons.get(instrument_name),
            calculation=calculation,
        )
        rank_inputs = _rank_inputs(
            instrument=instrument,
            detector_state=detector_state,
            calculation=calculation,
            regime=regime,
            surface=surface,
            legged=legged,
        )
        unranked[instrument_name] = ReviewContext(
            hard_screen_label=explanation.label,
            positive_witness=explanation.positive_witness,
            primary_blocker=explanation.blocker,
            upgrade_condition=explanation.upgrade_condition,
            invalidation_condition=explanation.invalidation_condition,
            regime=regime,
            surface=surface,
            legged_structure=legged,
            rank_inputs=rank_inputs,
            rank_explanation=_rank_explanation(rank_inputs),
        )

    ordered_names = sorted(
        unranked,
        key=lambda name: _rank_key(unranked[name].rank_inputs),
    )
    return {
        name: replace(
            unranked[name],
            attention_rank=rank,
            within_attention_top_n=rank <= attention_top_n,
        )
        for rank, name in enumerate(ordered_names, start=1)
    }


def build_score_feature_contexts(
    *,
    options: Mapping[str, OptionInstrument],
    calculations: Mapping[str, DetectorCalculation],
    tickers: Mapping[str, TickerState],
) -> dict[str, ScoreFeatureContext]:
    points = _surface_points(options, tickers)
    return {
        instrument_name: ScoreFeatureContext(
            option_type=instrument.option_type,
            regime=_regime_context(instrument.option_type, calculations.get(instrument_name)),
            surface=_surface_context(
                instrument=instrument,
                calculation=calculations.get(instrument_name),
                points=points,
            ),
        )
        for instrument_name, instrument in options.items()
    }


def _regime_context(
    option_type: OptionType,
    calculation: DetectorCalculation | None,
) -> RegimeContext:
    if calculation is None or not calculation.baseline.window_diagnostics:
        return RegimeContext(DiagnosticState.UNKNOWN)
    diagnostics = calculation.baseline.window_diagnostics
    selected_lookback = calculation.baseline.selected_lookback_minutes
    if selected_lookback is None:
        selected = max(
            diagnostics,
            key=lambda member: (
                member.variance_rate_per_minute,
                member.lookback_minutes,
            ),
        )
    else:
        selected = calculation.baseline.diagnostics_for(selected_lookback)
    adverse = (
        selected.positive_semivariance_share
        if option_type is OptionType.CALL
        else selected.negative_semivariance_share
    )
    return RegimeContext(
        state=DiagnosticState.AVAILABLE,
        lookback_minutes=selected.lookback_minutes,
        positive_semivariance_share=selected.positive_semivariance_share,
        negative_semivariance_share=selected.negative_semivariance_share,
        adverse_semivariance_share=adverse,
        jump_share=selected.jump_share,
        maximum_absolute_return=selected.maximum_absolute_return,
        net_return=selected.net_return,
    )


def _surface_points(
    options: Mapping[str, OptionInstrument],
    tickers: Mapping[str, TickerState],
) -> tuple[_SurfacePoint, ...]:
    points: list[_SurfacePoint] = []
    for instrument_name, instrument in options.items():
        ticker = tickers.get(instrument_name)
        if (
            ticker is None
            or ticker.signed_delta is None
            or ticker.mark_iv_fraction is None
            or not instrument.is_active
            or instrument.lifecycle_state is not InstrumentLifecycleState.OPEN
        ):
            continue
        abs_delta = abs(ticker.signed_delta)
        mark_iv = ticker.mark_iv_fraction
        if (
            not abs_delta.is_finite()
            or not Decimal(0) <= abs_delta <= Decimal(1)
            or not mark_iv.is_finite()
            or mark_iv <= 0
        ):
            continue
        points.append(
            _SurfacePoint(
                instrument_name=instrument_name,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                option_type=instrument.option_type,
                abs_delta=abs_delta,
                mark_iv=mark_iv,
            )
        )
    return tuple(points)


def _surface_context(
    *,
    instrument: OptionInstrument,
    calculation: DetectorCalculation | None,
    points: tuple[_SurfacePoint, ...],
) -> SurfaceContext:
    if calculation is None:
        return SurfaceContext(DiagnosticState.UNKNOWN)
    same_expiry = tuple(
        point
        for point in points
        if point.expiration_timestamp_ms == instrument.expiration_timestamp_ms
    )
    if not same_expiry:
        return SurfaceContext(DiagnosticState.UNKNOWN)

    atm = min(
        same_expiry,
        key=lambda point: (
            abs(point.abs_delta - TARGET_ATM_DELTA),
            point.instrument_name,
        ),
    )
    call_25 = _nearest_delta_point(same_expiry, OptionType.CALL, TARGET_TWENTY_FIVE_DELTA)
    put_25 = _nearest_delta_point(same_expiry, OptionType.PUT, TARGET_TWENTY_FIVE_DELTA)
    risk_reversal = (
        call_25.mark_iv - put_25.mark_iv if call_25 is not None and put_25 is not None else None
    )

    target_delta = _absolute_interval_midpoint(calculation.delta.lower, calculation.delta.upper)
    same_type = tuple(
        point
        for point in same_expiry
        if point.option_type is instrument.option_type
        and point.instrument_name != instrument.instrument_name
    )
    lower = max(
        (point for point in same_type if point.abs_delta < target_delta),
        key=lambda point: (point.abs_delta, point.instrument_name),
        default=None,
    )
    upper = min(
        (point for point in same_type if point.abs_delta > target_delta),
        key=lambda point: (point.abs_delta, point.instrument_name),
        default=None,
    )
    local_iv = _interpolate_mark_iv(lower, upper, target_delta)
    executable_midpoint = _interval_midpoint(
        calculation.stressed_executable_bid_iv.lower,
        calculation.stressed_executable_bid_iv.upper,
    )
    residual = executable_midpoint - local_iv if local_iv is not None else None

    adjacent = _adjacent_expiry_atm(
        points,
        current_expiry_ms=instrument.expiration_timestamp_ms,
    )
    adjacent_difference = atm.mark_iv - adjacent.mark_iv if adjacent is not None else None

    primary_values = (atm.mark_iv, risk_reversal, local_iv, adjacent_difference)
    state = (
        DiagnosticState.AVAILABLE
        if all(value is not None for value in primary_values)
        else DiagnosticState.PARTIAL
    )
    return SurfaceContext(
        state=state,
        same_expiry_atm_instrument_name=atm.instrument_name,
        same_expiry_atm_abs_delta=atm.abs_delta,
        same_expiry_atm_mark_iv=atm.mark_iv,
        nearest_25d_call_instrument_name=(call_25.instrument_name if call_25 is not None else None),
        nearest_25d_call_abs_delta=call_25.abs_delta if call_25 is not None else None,
        nearest_25d_call_mark_iv=call_25.mark_iv if call_25 is not None else None,
        nearest_25d_put_instrument_name=(put_25.instrument_name if put_25 is not None else None),
        nearest_25d_put_abs_delta=put_25.abs_delta if put_25 is not None else None,
        nearest_25d_put_mark_iv=put_25.mark_iv if put_25 is not None else None,
        twenty_five_delta_risk_reversal=risk_reversal,
        local_lower_instrument_name=lower.instrument_name if lower is not None else None,
        local_lower_abs_delta=lower.abs_delta if lower is not None else None,
        local_lower_mark_iv=lower.mark_iv if lower is not None else None,
        local_upper_instrument_name=upper.instrument_name if upper is not None else None,
        local_upper_abs_delta=upper.abs_delta if upper is not None else None,
        local_upper_mark_iv=upper.mark_iv if upper is not None else None,
        local_interpolated_mark_iv=local_iv,
        stressed_executable_bid_iv_midpoint=executable_midpoint,
        stressed_executable_bid_iv_minus_local_mark_iv=residual,
        adjacent_expiry_timestamp_ms=(
            adjacent.expiration_timestamp_ms if adjacent is not None else None
        ),
        adjacent_expiry_atm_instrument_name=(
            adjacent.instrument_name if adjacent is not None else None
        ),
        adjacent_expiry_atm_mark_iv=adjacent.mark_iv if adjacent is not None else None,
        current_minus_adjacent_expiry_atm_iv=adjacent_difference,
    )


def _nearest_delta_point(
    points: tuple[_SurfacePoint, ...],
    option_type: OptionType,
    target: Decimal,
) -> _SurfacePoint | None:
    candidates = tuple(point for point in points if point.option_type is option_type)
    if not candidates:
        return None
    nearest = min(
        candidates,
        key=lambda point: (abs(point.abs_delta - target), point.instrument_name),
    )
    return nearest if abs(nearest.abs_delta - target) <= FIVE_DELTA_POINTS else None


def _interpolate_mark_iv(
    lower: _SurfacePoint | None,
    upper: _SurfacePoint | None,
    target_delta: Decimal,
) -> Decimal | None:
    if lower is None or upper is None or upper.abs_delta <= lower.abs_delta:
        return None
    weight = (target_delta - lower.abs_delta) / (upper.abs_delta - lower.abs_delta)
    return lower.mark_iv + weight * (upper.mark_iv - lower.mark_iv)


def _adjacent_expiry_atm(
    points: tuple[_SurfacePoint, ...],
    *,
    current_expiry_ms: int,
) -> _SurfacePoint | None:
    by_expiry: dict[int, list[_SurfacePoint]] = {}
    for point in points:
        if point.expiration_timestamp_ms > current_expiry_ms:
            by_expiry.setdefault(point.expiration_timestamp_ms, []).append(point)
    if not by_expiry:
        return None
    expiry = min(by_expiry)
    return min(
        by_expiry[expiry],
        key=lambda point: (
            abs(point.abs_delta - TARGET_ATM_DELTA),
            point.instrument_name,
        ),
    )


def _legged_structure_context(
    *,
    short_instrument: OptionInstrument,
    calculation: DetectorCalculation | None,
    options: Mapping[str, OptionInstrument],
    option_books: Mapping[str, ContinuousOrderBook],
    option_catalog_complete: bool,
    index_usdc_per_btc: Decimal | None,
    target_quantity_btc: Decimal,
    fee_rate_index_fraction: Decimal,
) -> LeggedStructureContext:
    if calculation is None:
        return LeggedStructureContext(
            LeggedReferenceState.UNKNOWN,
            missing_reasons=("SHORT_LEG_FORMULA_UNAVAILABLE",),
        )
    protective = tuple(
        candidate
        for candidate in options.values()
        if _is_protective_leg(short_instrument, candidate)
    )
    if not protective:
        return LeggedStructureContext(
            (
                LeggedReferenceState.NO_PROTECTIVE_LEG
                if option_catalog_complete
                else LeggedReferenceState.UNKNOWN
            ),
            missing_reasons=(() if option_catalog_complete else ("OPTION_CATALOG_INCOMPLETE",)),
        )

    references: list[LeggedVerticalReference] = []
    missing: set[str] = set()
    if index_usdc_per_btc is None or not index_usdc_per_btc.is_finite() or index_usdc_per_btc <= 0:
        missing.add("CURRENT_INDEX_UNKNOWN")
    else:
        for long_instrument in protective:
            reference, reasons = _legged_reference(
                short_instrument=short_instrument,
                long_instrument=long_instrument,
                short_book=option_books.get(short_instrument.instrument_name),
                long_book=option_books.get(long_instrument.instrument_name),
                index_usdc_per_btc=index_usdc_per_btc,
                target_quantity_btc=target_quantity_btc,
                fee_rate_index_fraction=fee_rate_index_fraction,
            )
            missing.update(reasons)
            if reference is not None:
                references.append(reference)

    references.sort(
        key=lambda value: (
            -value.credit_to_payoff_cap_fraction,
            -value.stressed_net_credit_usdc,
            value.width_usdc_per_btc,
            value.long_instrument_name,
        )
    )
    selected = tuple(references[:3])
    if selected:
        return LeggedStructureContext(
            LeggedReferenceState.LEGGED_REFERENCE_NOT_ATOMIC,
            references=selected,
            missing_reasons=tuple(sorted(missing)),
        )
    if not option_catalog_complete:
        missing.add("OPTION_CATALOG_INCOMPLETE")
        state = LeggedReferenceState.UNKNOWN
    else:
        state = LeggedReferenceState.NO_TARGET_SIZE_REFERENCE
    return LeggedStructureContext(state, missing_reasons=tuple(sorted(missing)))


def _legged_reference(
    *,
    short_instrument: OptionInstrument,
    long_instrument: OptionInstrument,
    short_book: ContinuousOrderBook | None,
    long_book: ContinuousOrderBook | None,
    index_usdc_per_btc: Decimal,
    target_quantity_btc: Decimal,
    fee_rate_index_fraction: Decimal,
) -> tuple[LeggedVerticalReference | None, tuple[str, ...]]:
    reasons: list[str] = []
    if short_book is None or short_book.state is not BookState.USABLE:
        reasons.append(f"{short_instrument.instrument_name}:BOOK_UNKNOWN")
    if long_book is None or long_book.state is not BookState.USABLE:
        reasons.append(f"{long_instrument.instrument_name}:BOOK_UNKNOWN")
    if reasons:
        return None, tuple(reasons)
    assert short_book is not None
    assert long_book is not None
    quote, quote_reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.ENTRY,
        short_instrument=short_instrument,
        long_instrument=long_instrument,
        short_side_levels=short_book.levels("bid"),
        long_side_levels=long_book.levels("ask"),
        index_usdc_per_btc=index_usdc_per_btc,
        target_quantity_btc=target_quantity_btc,
        fee_rate_index_fraction=fee_rate_index_fraction,
    )
    if quote is None:
        return None, tuple(
            f"{long_instrument.instrument_name}:{reason}" for reason in quote_reasons
        )
    return (
        LeggedVerticalReference(
            long_instrument_name=long_instrument.instrument_name,
            product_spec_identity=quote.product_spec_identity,
            product_name=quote.product_name,
            native_premium_currency=quote.native_premium_currency,
            valuation_currency=quote.valuation_currency,
            strike_currency=short_instrument.product.strike_currency,
            valuation_index_price=quote.valuation_index_price,
            short_strike_usdc_per_btc=short_instrument.strike,
            long_strike_usdc_per_btc=long_instrument.strike,
            raw_short_bid_vwap_usdc_per_btc=quote.short_leg.raw.vwap,
            stressed_short_bid_vwap_usdc_per_btc=quote.short_leg.stressed.vwap,
            raw_long_ask_vwap_usdc_per_btc=quote.long_leg.raw.vwap,
            stressed_long_ask_vwap_usdc_per_btc=quote.long_leg.stressed.vwap,
            stressed_gross_credit_usdc=quote.gross_cashflow_usdc,
            short_fee_reserve_usdc=quote.short_leg.fee_reserve_usdc,
            long_fee_reserve_usdc=quote.long_leg.fee_reserve_usdc,
            total_fee_reserve_usdc=quote.total_fee_reserve_usdc,
            stressed_net_credit_usdc=quote.net_cashflow_usdc,
            stressed_gross_credit_native=quote.native_gross_cashflow,
            short_fee_reserve_native=quote.short_leg.native_fee_reserve,
            long_fee_reserve_native=quote.long_leg.native_fee_reserve,
            total_fee_reserve_native=quote.native_total_fee_reserve,
            stressed_net_credit_native=quote.native_net_cashflow,
            width_usdc_per_btc=quote.width_usdc_per_btc,
            payoff_cap_usdc=quote.payoff_cap_usdc,
            maximum_loss_after_fee_reserve_usdc=max(
                Decimal(0), quote.payoff_cap_usdc - quote.net_cashflow_usdc
            ),
            credit_to_payoff_cap_fraction=(quote.net_cashflow_usdc / quote.payoff_cap_usdc),
        ),
        (),
    )


def _is_protective_leg(short: OptionInstrument, candidate: OptionInstrument) -> bool:
    if (
        candidate.instrument_name == short.instrument_name
        or candidate.product != short.product
        or candidate.expiration_timestamp_ms != short.expiration_timestamp_ms
        or candidate.option_type is not short.option_type
        or not candidate.is_active
        or candidate.lifecycle_state is not InstrumentLifecycleState.OPEN
    ):
        return False
    if short.option_type is OptionType.CALL:
        return candidate.strike > short.strike
    return candidate.strike < short.strike


def _hard_screen_explanation(
    *,
    detector_state: DetectorState,
    detector_reason: str | None,
    calculation: DetectorCalculation | None,
) -> _HardScreenExplanation:
    if calculation is None:
        return _HardScreenExplanation(
            label="HARD_SCREEN_UNAVAILABLE",
            positive_witness="NONE",
            blocker=detector_reason or "REQUIRED_HARD_SCREEN_FACTS_UNAVAILABLE",
            upgrade_condition="RESTORE_REQUIRED_HARD_SCREEN_FACTS",
            invalidation_condition="NOT_APPLICABLE_WITHOUT_A_KNOWN_FORMULA",
        )
    if detector_state is DetectorState.ANOMALY_ACTIVE:
        score_result = calculation.score_result
        score_witness = (
            f"V2_SCORE_LOWER={score_result.score.lower};"
            f"PREMIUM_EVIDENCE_LOWER={score_result.premium_evidence.lower};"
            f"RISK_QUALITY_LOWER={score_result.risk_quality.lower}"
            if score_result is not None
            else "V2_SCORE_RESULT_NOT_ATTACHED"
        )
        return _HardScreenExplanation(
            label="V2_SCORE_EPISODE_ACTIVE",
            positive_witness=score_witness,
            blocker="NONE_AT_RADAR_HARD_SCREEN",
            upgrade_condition="OFFICIAL_ATOMIC_QUOTE_THEN_UNDERWRITING",
            invalidation_condition=("SOURCE_LOSS_OR_SCORE_CLEAR_THRESHOLD_CONFIRMED"),
        )
    if not calculation.band.clue_eligible and not calculation.delta_clue_eligible:
        label = "REVIEW_ONLY_TTE_AND_DELTA"
        upgrade = "ENTER_CLUE_ELIGIBLE_TTE_AND_DELTA_BUCKETS"
    elif not calculation.band.clue_eligible:
        label = "REVIEW_ONLY_TTE"
        upgrade = "ENTER_CLUE_ELIGIBLE_TTE_BUCKET"
    elif not calculation.delta_clue_eligible:
        label = "REVIEW_ONLY_DELTA"
        upgrade = "ENTER_CLUE_ELIGIBLE_DELTA_BUCKET"
    else:
        label = "V2_SCORE_KNOWN_NOT_ACTIVE"
        upgrade = "MEET_SCORE_65_AND_TIME_PERSISTENCE"
    return _HardScreenExplanation(
        label=label,
        positive_witness="V2_CORE_FORMULA_KNOWN",
        blocker=detector_reason or "V2_SCORE_OR_PERSISTENCE_NOT_ACTIVE",
        upgrade_condition=upgrade,
        invalidation_condition="SOURCE_LOSS_OR_KNOWN_FORMULA_INELIGIBILITY",
    )


def _rank_inputs(
    *,
    instrument: OptionInstrument,
    detector_state: DetectorState,
    calculation: DetectorCalculation | None,
    regime: RegimeContext,
    surface: SurfaceContext,
    legged: LeggedStructureContext,
) -> RankInputs:
    return RankInputs(
        detector_state=detector_state,
        formula_available=calculation is not None,
        clue_eligible_tte=(calculation.band.clue_eligible if calculation is not None else False),
        clue_eligible_delta=(calculation.delta_clue_eligible if calculation is not None else False),
        stressed_richness_lower=(calculation.richness.lower if calculation is not None else None),
        surface_residual=surface.stressed_executable_bid_iv_minus_local_mark_iv,
        best_legged_credit_to_payoff_cap_fraction=(legged.best_credit_to_payoff_cap_fraction),
        adverse_semivariance_share=regime.adverse_semivariance_share,
        jump_share=regime.jump_share,
        target_spread_ticks=(calculation.target_spread_ticks if calculation is not None else None),
        consumed_level_count=(
            len(calculation.target_bid.consumed) + len(calculation.target_ask.consumed)
            if calculation is not None
            else None
        ),
        expiration_timestamp_ms=instrument.expiration_timestamp_ms,
        option_type=instrument.option_type,
        abs_delta_midpoint=(
            _absolute_interval_midpoint(calculation.delta.lower, calculation.delta.upper)
            if calculation is not None
            else None
        ),
        strike_usdc_per_btc=instrument.strike,
        instrument_name=instrument.instrument_name,
    )


def _rank_key(value: RankInputs) -> tuple[object, ...]:
    active_priority = 0 if value.detector_state is DetectorState.ANOMALY_ACTIVE else 1
    clue_priority = 0 if value.clue_eligible else 1
    surface_missing = 0 if value.surface_residual is not None else 1
    legged_missing = 0 if value.best_legged_credit_to_payoff_cap_fraction is not None else 1
    option_type_priority = 0 if value.option_type is OptionType.CALL else 1
    return (
        active_priority,
        clue_priority,
        _descending(value.stressed_richness_lower),
        surface_missing,
        _descending(value.surface_residual),
        legged_missing,
        _descending(value.best_legged_credit_to_payoff_cap_fraction),
        _ascending(value.adverse_semivariance_share),
        _ascending(value.jump_share),
        _ascending(value.target_spread_ticks),
        value.consumed_level_count if value.consumed_level_count is not None else 1_000_000,
        value.expiration_timestamp_ms,
        option_type_priority,
        _ascending(value.abs_delta_midpoint),
        value.strike_usdc_per_btc,
        value.instrument_name,
    )


def _rank_explanation(value: RankInputs) -> tuple[str, ...]:
    return (
        f"detector_state={value.detector_state.value}",
        f"clue_eligible_tte={str(value.clue_eligible_tte).lower()}",
        f"clue_eligible_delta={str(value.clue_eligible_delta).lower()}",
        f"stressed_richness_lower={_text_or_unknown(value.stressed_richness_lower)}",
        f"surface_residual={_text_or_unknown(value.surface_residual)}",
        "best_legged_credit_to_payoff_cap_fraction="
        f"{_text_or_unknown(value.best_legged_credit_to_payoff_cap_fraction)}",
        f"adverse_semivariance_share={_text_or_unknown(value.adverse_semivariance_share)}",
        f"jump_share={_text_or_unknown(value.jump_share)}",
        f"target_spread_ticks={_text_or_unknown(value.target_spread_ticks)}",
        f"consumed_level_count={value.consumed_level_count}",
        "deterministic_tie_breaker="
        f"{value.expiration_timestamp_ms}:{value.option_type.value}:"
        f"{_text_or_unknown(value.abs_delta_midpoint)}:{value.strike_usdc_per_btc}:"
        f"{value.instrument_name}",
    )


def _descending(value: Decimal | None) -> Decimal:
    return _LARGE_RANK_VALUE if value is None else -value


def _ascending(value: Decimal | None) -> Decimal:
    return _LARGE_RANK_VALUE if value is None else value


def _interval_midpoint(lower: Decimal, upper: Decimal) -> Decimal:
    return (lower + upper) / Decimal(2)


def _absolute_interval_midpoint(lower: Decimal, upper: Decimal) -> Decimal:
    absolute = tuple(abs(value) for value in (lower, upper))
    return (min(absolute) + max(absolute)) / Decimal(2)


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _text_or_unknown(value: Decimal | None) -> str:
    return "UNKNOWN" if value is None else str(value)


__all__ = [
    "DEFAULT_ATTENTION_TOP_N",
    "LEGGED_REFERENCE_NON_CLAIMS",
    "DiagnosticState",
    "LeggedReferenceState",
    "LeggedStructureContext",
    "LeggedVerticalReference",
    "RankInputs",
    "RegimeContext",
    "ReviewContext",
    "ScoreFeatureContext",
    "SurfaceContext",
    "build_review_contexts",
    "build_score_feature_contexts",
]
