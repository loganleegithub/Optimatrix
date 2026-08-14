from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from optimatrix.channels import ChannelId
from optimatrix.identity import canonical_identity
from optimatrix.session import SessionPhasePolicy

DEFAULT_BTC_SHORT_VOL_POLICY_PATH = (
    Path(__file__).parent / "data" / "btc-inverse-0dte-two-sided-short-vol.json"
)


@dataclass(frozen=True)
class WindowSchedulePolicy:
    cadence_minutes: int
    alignment: str
    input_grace_seconds: int

    def __post_init__(self) -> None:
        if self.cadence_minutes <= 0 or 24 * 60 % self.cadence_minutes != 0:
            raise ValueError("window cadence must be a positive divisor of one Deribit session")
        if self.alignment != "SESSION_START":
            raise ValueError("window alignment must be SESSION_START")
        if not 0 <= self.input_grace_seconds < self.cadence_minutes * 60:
            raise ValueError("window input grace must be non-negative and shorter than cadence")

    @property
    def identity(self) -> str:
        return canonical_identity(
            "WindowSchedulePolicyV1",
            self.cadence_minutes,
            self.alignment,
            self.input_grace_seconds,
        )


@dataclass(frozen=True)
class ObservationPolicy:
    maximum_source_span_ms: int
    maximum_receive_span_ms: int
    maximum_age_ms: int

    @property
    def identity(self) -> str:
        return canonical_identity(
            "ObservationPolicyV1",
            self.maximum_source_span_ms,
            self.maximum_receive_span_ms,
            self.maximum_age_ms,
        )


@dataclass(frozen=True)
class EnvironmentPolicy:
    minimum_vrp_ratio: Decimal
    late_theta_minimum_vrp_ratio: Decimal
    maximum_rv_acceleration: Decimal
    maximum_jump_share: Decimal
    maximum_directional_persistence: Decimal


@dataclass(frozen=True)
class StructurePolicy:
    option_amount: Decimal
    short_delta_min: Decimal
    short_delta_max: Decimal
    minimum_wing_width_usd: Decimal
    maximum_wing_width_usd: Decimal
    minimum_body_distance_sigma: Decimal
    maximum_abs_net_delta: Decimal
    maximum_retained_alternatives: int


@dataclass(frozen=True)
class UnderwritingPolicy:
    minimum_boundary_net_credit_usd: Decimal
    minimum_credit_to_payoff_cap: Decimal
    maximum_boundary_reference_loss_usd: Decimal
    maximum_combo_fee_fraction_of_credit: Decimal


@dataclass(frozen=True)
class ShadowRiskPolicy:
    maximum_session_stress_reserve_usd: Decimal
    maximum_concurrent_positions: int
    delivery_price_stress_factors: tuple[Decimal, ...]
    exit_cost_stress_fraction: Decimal


@dataclass(frozen=True)
class LifecyclePolicy:
    entry_evaluation_window_seconds: int
    monitoring_cadence_seconds: int
    take_profit_fraction_of_credit: Decimal
    maximum_loss_multiple_of_credit: Decimal
    maximum_short_abs_delta: Decimal
    maximum_adverse_move_fraction: Decimal
    maximum_rv_acceleration: Decimal
    latest_exit_minutes_to_expiry: int
    trigger_priority: tuple[str, ...]


@dataclass(frozen=True)
class BtcShortVolPolicy:
    schema_version: int
    policy_name: str
    channel_id: ChannelId
    status: str
    window: WindowSchedulePolicy
    observation: ObservationPolicy
    session: SessionPhasePolicy
    environment: EnvironmentPolicy
    structure: StructurePolicy
    underwriting: UnderwritingPolicy
    risk: ShadowRiskPolicy
    lifecycle: LifecyclePolicy

    @property
    def identity(self) -> str:
        return canonical_identity(
            "BtcTwoSidedShortVolPolicyV8",
            self.schema_version,
            self.policy_name,
            self.channel_id,
            self.status,
            self.window,
            self.observation,
            self.session,
            self.environment,
            self.structure,
            self.underwriting,
            self.risk,
            self.lifecycle,
        )


def load_btc_short_vol_policy(path: Path) -> BtcShortVolPolicy:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("policy root must be an object")
    expected = {
        "schema_version",
        "policy_name",
        "channel_id",
        "status",
        "window",
        "observation",
        "session",
        "environment",
        "structure",
        "underwriting",
        "risk",
        "lifecycle",
    }
    if set(raw) != expected:
        raise ValueError("policy root has unexpected fields")
    channel_id = ChannelId(_text(raw, "channel_id"))
    if channel_id is not ChannelId.INVERSE_BTC_SHORT_VOL:
        raise ValueError("policy is not the implemented BTC Short Vol channel")

    window = _mapping(raw, "window")
    observation = _mapping(raw, "observation")
    session = _mapping(raw, "session")
    environment = _mapping(raw, "environment")
    structure = _mapping(raw, "structure")
    if set(structure) != {
        "option_amount",
        "short_delta_min",
        "short_delta_max",
        "minimum_wing_width_usd",
        "maximum_wing_width_usd",
        "minimum_body_distance_sigma",
        "maximum_abs_net_delta",
        "maximum_retained_alternatives",
    }:
        raise ValueError("structure policy has unexpected fields")
    underwriting = _mapping(raw, "underwriting")
    risk = _mapping(raw, "risk")
    lifecycle = _mapping(raw, "lifecycle")

    policy = BtcShortVolPolicy(
        schema_version=_positive_int(raw, "schema_version"),
        policy_name=_text(raw, "policy_name"),
        channel_id=channel_id,
        status=_text(raw, "status"),
        window=WindowSchedulePolicy(
            cadence_minutes=_positive_int(window, "cadence_minutes"),
            alignment=_text(window, "alignment"),
            input_grace_seconds=_non_negative_int(window, "input_grace_seconds"),
        ),
        observation=ObservationPolicy(
            maximum_source_span_ms=_positive_int(observation, "maximum_source_span_ms"),
            maximum_receive_span_ms=_positive_int(observation, "maximum_receive_span_ms"),
            maximum_age_ms=_positive_int(observation, "maximum_age_ms"),
        ),
        session=SessionPhasePolicy(
            roll_reprice_minutes=_positive_int(session, "roll_reprice_minutes"),
            late_theta_start_minutes_to_expiry=_positive_int(
                session, "late_theta_start_minutes_to_expiry"
            ),
            exit_only_minutes_to_expiry=_positive_int(session, "exit_only_minutes_to_expiry"),
            delivery_twap_minutes_to_expiry=_positive_int(
                session, "delivery_twap_minutes_to_expiry"
            ),
        ),
        environment=EnvironmentPolicy(
            minimum_vrp_ratio=_decimal(environment, "minimum_vrp_ratio"),
            late_theta_minimum_vrp_ratio=_decimal(environment, "late_theta_minimum_vrp_ratio"),
            maximum_rv_acceleration=_decimal(environment, "maximum_rv_acceleration"),
            maximum_jump_share=_decimal(environment, "maximum_jump_share"),
            maximum_directional_persistence=_decimal(
                environment, "maximum_directional_persistence"
            ),
        ),
        structure=StructurePolicy(
            option_amount=_decimal(structure, "option_amount"),
            short_delta_min=_decimal(structure, "short_delta_min"),
            short_delta_max=_decimal(structure, "short_delta_max"),
            minimum_wing_width_usd=_decimal(structure, "minimum_wing_width_usd"),
            maximum_wing_width_usd=_decimal(structure, "maximum_wing_width_usd"),
            minimum_body_distance_sigma=_decimal(structure, "minimum_body_distance_sigma"),
            maximum_abs_net_delta=_decimal(structure, "maximum_abs_net_delta"),
            maximum_retained_alternatives=_positive_int(structure, "maximum_retained_alternatives"),
        ),
        underwriting=UnderwritingPolicy(
            minimum_boundary_net_credit_usd=_decimal(
                underwriting, "minimum_boundary_net_credit_usd"
            ),
            minimum_credit_to_payoff_cap=_decimal(underwriting, "minimum_credit_to_payoff_cap"),
            maximum_boundary_reference_loss_usd=_decimal(
                underwriting, "maximum_boundary_reference_loss_usd"
            ),
            maximum_combo_fee_fraction_of_credit=_decimal(
                underwriting, "maximum_combo_fee_fraction_of_credit"
            ),
        ),
        risk=ShadowRiskPolicy(
            maximum_session_stress_reserve_usd=_decimal(risk, "maximum_session_stress_reserve_usd"),
            maximum_concurrent_positions=_positive_int(risk, "maximum_concurrent_positions"),
            delivery_price_stress_factors=_decimal_tuple(risk, "delivery_price_stress_factors"),
            exit_cost_stress_fraction=_decimal(risk, "exit_cost_stress_fraction"),
        ),
        lifecycle=LifecyclePolicy(
            entry_evaluation_window_seconds=_positive_int(
                lifecycle, "entry_evaluation_window_seconds"
            ),
            monitoring_cadence_seconds=_positive_int(lifecycle, "monitoring_cadence_seconds"),
            take_profit_fraction_of_credit=_decimal(lifecycle, "take_profit_fraction_of_credit"),
            maximum_loss_multiple_of_credit=_decimal(lifecycle, "maximum_loss_multiple_of_credit"),
            maximum_short_abs_delta=_decimal(lifecycle, "maximum_short_abs_delta"),
            maximum_adverse_move_fraction=_decimal(lifecycle, "maximum_adverse_move_fraction"),
            maximum_rv_acceleration=_decimal(lifecycle, "maximum_rv_acceleration"),
            latest_exit_minutes_to_expiry=_positive_int(lifecycle, "latest_exit_minutes_to_expiry"),
            trigger_priority=_text_tuple(lifecycle, "trigger_priority"),
        ),
    )
    _validate(policy)
    return policy


def _validate(policy: BtcShortVolPolicy) -> None:
    if policy.schema_version != 8:
        raise ValueError("unsupported policy schema")
    if policy.status != "PUBLIC_SHADOW_UNQUALIFIED":
        raise ValueError("policy status must be PUBLIC_SHADOW_UNQUALIFIED")
    session = policy.session
    if session.roll_reprice_minutes + session.exit_only_minutes_to_expiry >= 24 * 60:
        raise ValueError("session phases leave no entry-capable time")

    environment = policy.environment
    if not Decimal(1) < environment.minimum_vrp_ratio <= environment.late_theta_minimum_vrp_ratio:
        raise ValueError("VRP thresholds are invalid")
    for value, name in (
        (environment.maximum_rv_acceleration, "maximum_rv_acceleration"),
        (environment.maximum_jump_share, "maximum_jump_share"),
        (environment.maximum_directional_persistence, "maximum_directional_persistence"),
    ):
        _fraction(value, name)

    structure = policy.structure
    if structure.option_amount <= 0:
        raise ValueError("option_amount must be positive")
    if not Decimal(0) < structure.short_delta_min < structure.short_delta_max <= Decimal(1):
        raise ValueError("short Delta interval is invalid")
    if not Decimal(0) < structure.maximum_abs_net_delta <= Decimal(1):
        raise ValueError("maximum_abs_net_delta must be in (0, 1]")
    if structure.minimum_body_distance_sigma <= 0:
        raise ValueError("minimum_body_distance_sigma must be positive")
    if structure.minimum_wing_width_usd <= 0 or (
        structure.maximum_wing_width_usd <= structure.minimum_wing_width_usd
    ):
        raise ValueError("wing width interval is invalid")

    underwriting = policy.underwriting
    if underwriting.minimum_boundary_net_credit_usd <= 0:
        raise ValueError("minimum boundary credit must be positive")
    _fraction(underwriting.minimum_credit_to_payoff_cap, "minimum_credit_to_payoff_cap")
    _fraction(
        underwriting.maximum_combo_fee_fraction_of_credit,
        "maximum_combo_fee_fraction_of_credit",
    )
    if underwriting.maximum_boundary_reference_loss_usd <= 0:
        raise ValueError("maximum boundary reference loss must be positive")

    risk = policy.risk
    if risk.maximum_session_stress_reserve_usd <= 0:
        raise ValueError("maximum Session stress reserve must be positive")
    if not risk.delivery_price_stress_factors or any(
        factor <= 0 for factor in risk.delivery_price_stress_factors
    ):
        raise ValueError("delivery stress factors must be positive")
    _fraction(risk.exit_cost_stress_fraction, "exit_cost_stress_fraction")

    lifecycle = policy.lifecycle
    _fraction(lifecycle.take_profit_fraction_of_credit, "take_profit_fraction_of_credit")
    if lifecycle.take_profit_fraction_of_credit == 0:
        raise ValueError("take-profit fraction must be positive")
    if lifecycle.maximum_loss_multiple_of_credit <= 0:
        raise ValueError("maximum loss multiple must be positive")
    if not Decimal(0) < lifecycle.maximum_short_abs_delta <= Decimal(1):
        raise ValueError("maximum short Delta must be in (0, 1]")
    _fraction(lifecycle.maximum_adverse_move_fraction, "maximum_adverse_move_fraction")
    _fraction(lifecycle.maximum_rv_acceleration, "lifecycle maximum_rv_acceleration")
    if not (
        session.delivery_twap_minutes_to_expiry
        <= lifecycle.latest_exit_minutes_to_expiry
        <= session.exit_only_minutes_to_expiry
    ):
        raise ValueError("latest exit must be inside the declared exit phase")
    required_triggers = {
        "LATEST_EXIT",
        "EVENT_OR_SHOCK",
        "MAXIMUM_LOSS",
        "SHORT_DELTA",
        "ADVERSE_MOVE",
        "RV_ACCELERATION",
        "VRP_PROXY_DISSIPATED",
        "TAKE_PROFIT",
    }
    if set(lifecycle.trigger_priority) != required_triggers:
        raise ValueError("trigger_priority must contain each implemented trigger exactly once")


def _fraction(value: Decimal, field: str) -> None:
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
        raise ValueError(f"{field} must be in [0, 1]")


def _mapping(value: dict[str, Any], field: str) -> dict[str, Any]:
    member = value.get(field)
    if not isinstance(member, dict):
        raise ValueError(f"{field} must be an object")
    return member


def _text(value: dict[str, Any], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise ValueError(f"{field} must be non-empty text")
    return member


def _positive_int(value: dict[str, Any], field: str) -> int:
    member = value.get(field)
    if isinstance(member, bool) or not isinstance(member, int) or member <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return member


def _non_negative_int(value: dict[str, Any], field: str) -> int:
    member = value.get(field)
    if isinstance(member, bool) or not isinstance(member, int) or member < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return member


def _decimal(value: dict[str, Any], field: str) -> Decimal:
    member = value.get(field)
    if isinstance(member, bool) or member is None:
        raise ValueError(f"{field} must be decimal-compatible")
    parsed = Decimal(str(member))
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _decimal_tuple(value: dict[str, Any], field: str) -> tuple[Decimal, ...]:
    member = value.get(field)
    if not isinstance(member, list):
        raise ValueError(f"{field} must be an array")
    return tuple(_decimal({field: item}, field) for item in member)


def _text_tuple(value: dict[str, Any], field: str) -> tuple[str, ...]:
    member = value.get(field)
    if not isinstance(member, list) or not member:
        raise ValueError(f"{field} must be a non-empty array")
    if not all(isinstance(item, str) and item for item in member):
        raise ValueError(f"{field} values must be non-empty text")
    if len(set(member)) != len(member):
        raise ValueError(f"{field} values must be unique")
    return tuple(member)
