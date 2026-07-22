"""Transparent, uncalibrated finite-horizon observed-path stress."""

from __future__ import annotations

from decimal import Decimal

from short_vol_radar.contracts import (
    BreakoutDirection,
    DecisionFrame,
    FiniteHorizonPathRisk,
    RadarPolicy,
    WindowObservation,
)


def _move_rate(observation: WindowObservation) -> Decimal | None:
    if observation.path is None:
        return None
    movement = max(
        observation.path.range_fraction,
        observation.path.realized_variation,
    )
    return movement / Decimal(observation.coverage.requested_seconds).sqrt()


def estimate_path_risk(
    frame: DecisionFrame,
    horizon_seconds: int,
    *,
    policy: RadarPolicy | None = None,
) -> FiniteHorizonPathRisk:
    active = policy or RadarPolicy()
    complete_paths = tuple(
        item for item in frame.windows if item.coverage.price_complete and item.path is not None
    )
    complete_flows = tuple(
        item for item in frame.windows if item.coverage.trade_complete and item.flow is not None
    )
    reasons: list[str] = []
    if not frame.complete:
        reasons.extend(frame.completeness_reasons)
    if len(complete_paths) != len(frame.windows):
        reasons.append("REQUIRED_PATH_WINDOW_UNKNOWN")
    if len(complete_flows) != len(frame.windows):
        reasons.append("REQUIRED_FLOW_WINDOW_UNKNOWN")
    if reasons:
        return FiniteHorizonPathRisk(
            method_id="OBSERVED_PATH_STRESS_FIXED_PRIOR",
            frame_capture_seq=frame.as_of_capture_seq,
            horizon_seconds=horizon_seconds,
            complete=False,
            base_move_fraction=None,
            up_stress_move_fraction=None,
            down_stress_move_fraction=None,
            acceleration_ratio=None,
            directional_efficiency=None,
            maximum_step_fraction=None,
            directional_flow_score=None,
            breakout=BreakoutDirection.NONE,
            multiplier_terms=(),
            incomplete_reasons=tuple(dict.fromkeys(reasons)),
        )
    long_window = max(
        complete_paths,
        key=lambda item: item.coverage.requested_seconds,
    )
    short_window = min(
        complete_paths,
        key=lambda item: item.coverage.requested_seconds,
    )
    long_rate = _move_rate(long_window)
    short_rate = _move_rate(short_window)
    if long_rate is None or short_rate is None:
        raise RuntimeError("complete path observations lost movement rates")
    base_move = max(
        active.minimum_move_floor_fraction,
        long_rate * Decimal(horizon_seconds).sqrt(),
    )
    acceleration_ratio = (
        short_rate / long_rate - Decimal("1")
        if long_rate > 0
        else Decimal("0")
        if short_rate == 0
        else Decimal("1")
    )
    short_path = short_window.path
    long_path = long_window.path
    if short_path is None or long_path is None:
        raise RuntimeError("complete path observation lost its metrics")
    directional_efficiency = max(
        short_path.directional_efficiency,
        long_path.directional_efficiency,
    )
    maximum_step = max(
        short_path.maximum_step_fraction,
        long_path.maximum_step_fraction,
    )
    flow_window = min(
        complete_flows,
        key=lambda item: item.coverage.requested_seconds,
    )
    if flow_window.flow is None:
        raise RuntimeError("complete flow observation lost its metrics")
    directional_flow = max(
        Decimal("-1"),
        min(
            Decimal("1"),
            (flow_window.flow.aggressor_imbalance + flow_window.flow.liquidation_fraction)
            / Decimal("2"),
        ),
    )
    acceleration_term = min(Decimal("1"), max(Decimal("0"), acceleration_ratio)) * Decimal("0.5")
    trend_term = directional_efficiency * Decimal("0.5")
    jump_term = (
        min(Decimal("1"), maximum_step / base_move) * Decimal("0.5")
        if base_move > 0
        else Decimal("0")
    )
    quote_age_term = (
        min(
            Decimal("0.5"),
            Decimal(frame.surface.quote_age_dispersion_ms) / Decimal("10000"),
        )
        if frame.surface.quote_age_dispersion_ms is not None
        else Decimal("0.25")
    )
    common_multiplier = Decimal("1") + acceleration_term + trend_term + jump_term + quote_age_term
    up_flow_term = max(Decimal("0"), directional_flow) * Decimal("0.5")
    down_flow_term = max(Decimal("0"), -directional_flow) * Decimal("0.5")
    breakout = long_path.breakout
    up_breakout_term = Decimal("0.5") if breakout is BreakoutDirection.UP else Decimal("0")
    down_breakout_term = Decimal("0.5") if breakout is BreakoutDirection.DOWN else Decimal("0")
    return FiniteHorizonPathRisk(
        method_id="OBSERVED_PATH_STRESS_FIXED_PRIOR",
        frame_capture_seq=frame.as_of_capture_seq,
        horizon_seconds=horizon_seconds,
        complete=True,
        base_move_fraction=base_move,
        up_stress_move_fraction=(base_move * (common_multiplier + up_flow_term + up_breakout_term)),
        down_stress_move_fraction=(
            base_move * (common_multiplier + down_flow_term + down_breakout_term)
        ),
        acceleration_ratio=acceleration_ratio,
        directional_efficiency=directional_efficiency,
        maximum_step_fraction=maximum_step,
        directional_flow_score=directional_flow,
        breakout=breakout,
        multiplier_terms=(
            ("acceleration", acceleration_term),
            ("trend", trend_term),
            ("jump", jump_term),
            ("quote_age_uncertainty", quote_age_term),
            ("up_flow", up_flow_term),
            ("down_flow", down_flow_term),
            ("up_breakout", up_breakout_term),
            ("down_breakout", down_breakout_term),
        ),
        incomplete_reasons=(),
    )
