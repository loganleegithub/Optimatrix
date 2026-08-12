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
class RadarPolicy:
    minimum_vrp_ratio: Decimal
    late_theta_minimum_vrp_ratio: Decimal
    vrp_saturation_ratio: Decimal
    minimum_theta_capture_proxy: Decimal
    maximum_rv_acceleration: Decimal
    maximum_jump_share: Decimal
    maximum_directional_persistence: Decimal
    minimum_body_distance_sigma: Decimal
    maximum_abs_net_delta: Decimal
    activation_score: Decimal


@dataclass(frozen=True)
class StructurePolicy:
    target_quantity: Decimal
    short_delta_min: Decimal
    short_delta_max: Decimal
    minimum_wing_width_usd: Decimal
    maximum_wing_width_usd: Decimal
    top_verticals_per_side: int


@dataclass(frozen=True)
class UnderwritingPolicy:
    minimum_combined_net_credit_usd: Decimal
    minimum_credit_to_max_side_payoff: Decimal
    maximum_entry_boundary_loss_usd: Decimal
    maximum_total_fee_fraction_of_credit: Decimal


@dataclass(frozen=True)
class PositionPolicy:
    take_profit_fraction_of_credit: Decimal
    maximum_loss_multiple_of_credit: Decimal
    maximum_short_abs_delta: Decimal
    maximum_adverse_move_fraction: Decimal
    maximum_rv_acceleration: Decimal
    latest_short_risk_exit_minutes_to_expiry: int
    acquisition_retry_interval_ms: int
    allow_short_only_risk_exit: bool


@dataclass(frozen=True)
class ShadowPolicy:
    entry_acquisition_window_ms: int
    maximum_pair_source_skew_ms: int
    maximum_pair_receive_skew_ms: int
    maximum_position_quote_age_ms: int


@dataclass(frozen=True)
class BtcShortVolPolicy:
    schema_version: int
    policy_name: str
    channel_id: ChannelId
    status: str
    session: SessionPhasePolicy
    radar: RadarPolicy
    structure: StructurePolicy
    underwriting: UnderwritingPolicy
    position: PositionPolicy
    shadow: ShadowPolicy

    @property
    def identity(self) -> str:
        return canonical_identity(
            "BtcTwoSidedShortVolPolicyV1",
            self.schema_version,
            self.policy_name,
            self.channel_id,
            self.status,
            self.session,
            self.radar,
            self.structure,
            self.underwriting,
            self.position,
            self.shadow,
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
        "session",
        "radar",
        "structure",
        "underwriting",
        "position",
        "shadow",
    }
    if set(raw) != expected:
        raise ValueError("policy root has unexpected fields")
    channel_id = ChannelId(_text(raw, "channel_id"))
    if channel_id is not ChannelId.INVERSE_BTC_SHORT_VOL:
        raise ValueError("policy is not the implemented BTC Short Vol channel")
    session = _mapping(raw, "session")
    radar = _mapping(raw, "radar")
    structure = _mapping(raw, "structure")
    underwriting = _mapping(raw, "underwriting")
    position = _mapping(raw, "position")
    shadow = _mapping(raw, "shadow")
    policy = BtcShortVolPolicy(
        schema_version=_positive_int(raw, "schema_version"),
        policy_name=_text(raw, "policy_name"),
        channel_id=channel_id,
        status=_text(raw, "status"),
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
        radar=RadarPolicy(
            minimum_vrp_ratio=_decimal(radar, "minimum_vrp_ratio"),
            late_theta_minimum_vrp_ratio=_decimal(radar, "late_theta_minimum_vrp_ratio"),
            vrp_saturation_ratio=_decimal(radar, "vrp_saturation_ratio"),
            minimum_theta_capture_proxy=_decimal(radar, "minimum_theta_capture_proxy"),
            maximum_rv_acceleration=_decimal(radar, "maximum_rv_acceleration"),
            maximum_jump_share=_decimal(radar, "maximum_jump_share"),
            maximum_directional_persistence=_decimal(radar, "maximum_directional_persistence"),
            minimum_body_distance_sigma=_decimal(radar, "minimum_body_distance_sigma"),
            maximum_abs_net_delta=_decimal(radar, "maximum_abs_net_delta"),
            activation_score=_decimal(radar, "activation_score"),
        ),
        structure=StructurePolicy(
            target_quantity=_decimal(structure, "target_quantity"),
            short_delta_min=_decimal(structure, "short_delta_min"),
            short_delta_max=_decimal(structure, "short_delta_max"),
            minimum_wing_width_usd=_decimal(structure, "minimum_wing_width_usd"),
            maximum_wing_width_usd=_decimal(structure, "maximum_wing_width_usd"),
            top_verticals_per_side=_positive_int(structure, "top_verticals_per_side"),
        ),
        underwriting=UnderwritingPolicy(
            minimum_combined_net_credit_usd=_decimal(
                underwriting, "minimum_combined_net_credit_usd"
            ),
            minimum_credit_to_max_side_payoff=_decimal(
                underwriting, "minimum_credit_to_max_side_payoff"
            ),
            maximum_entry_boundary_loss_usd=_decimal(
                underwriting, "maximum_entry_boundary_loss_usd"
            ),
            maximum_total_fee_fraction_of_credit=_decimal(
                underwriting, "maximum_total_fee_fraction_of_credit"
            ),
        ),
        position=PositionPolicy(
            take_profit_fraction_of_credit=_decimal(position, "take_profit_fraction_of_credit"),
            maximum_loss_multiple_of_credit=_decimal(position, "maximum_loss_multiple_of_credit"),
            maximum_short_abs_delta=_decimal(position, "maximum_short_abs_delta"),
            maximum_adverse_move_fraction=_decimal(position, "maximum_adverse_move_fraction"),
            maximum_rv_acceleration=_decimal(position, "maximum_rv_acceleration"),
            latest_short_risk_exit_minutes_to_expiry=_positive_int(
                position, "latest_short_risk_exit_minutes_to_expiry"
            ),
            acquisition_retry_interval_ms=_positive_int(position, "acquisition_retry_interval_ms"),
            allow_short_only_risk_exit=_bool(position, "allow_short_only_risk_exit"),
        ),
        shadow=ShadowPolicy(
            entry_acquisition_window_ms=_positive_int(shadow, "entry_acquisition_window_ms"),
            maximum_pair_source_skew_ms=_positive_int(shadow, "maximum_pair_source_skew_ms"),
            maximum_pair_receive_skew_ms=_positive_int(shadow, "maximum_pair_receive_skew_ms"),
            maximum_position_quote_age_ms=_positive_int(shadow, "maximum_position_quote_age_ms"),
        ),
    )
    _validate(policy)
    return policy


def _validate(policy: BtcShortVolPolicy) -> None:
    if policy.schema_version != 1:
        raise ValueError("unsupported policy schema")
    if policy.status != "PUBLIC_SHADOW_UNQUALIFIED":
        raise ValueError("policy status must be PUBLIC_SHADOW_UNQUALIFIED")

    session = policy.session
    if session.roll_reprice_minutes >= 24 * 60:
        raise ValueError("roll/reprice phase must fit inside one Deribit session")
    if session.late_theta_start_minutes_to_expiry >= 24 * 60:
        raise ValueError("late-theta boundary must fit inside one Deribit session")
    if session.roll_reprice_minutes + session.exit_only_minutes_to_expiry >= 24 * 60:
        raise ValueError("roll/reprice and exit-only phases leave no entry-capable session")

    radar = policy.radar
    if not Decimal(1) < radar.minimum_vrp_ratio < radar.vrp_saturation_ratio:
        raise ValueError("VRP thresholds are invalid")
    if (
        not radar.minimum_vrp_ratio
        <= radar.late_theta_minimum_vrp_ratio
        < (radar.vrp_saturation_ratio)
    ):
        raise ValueError("late-theta VRP threshold is invalid")
    for value, field_name in (
        (radar.minimum_theta_capture_proxy, "minimum_theta_capture_proxy"),
        (radar.maximum_rv_acceleration, "maximum_rv_acceleration"),
        (radar.maximum_jump_share, "maximum_jump_share"),
        (radar.maximum_directional_persistence, "maximum_directional_persistence"),
        (radar.maximum_abs_net_delta, "maximum_abs_net_delta"),
    ):
        _fraction(value, field_name)
    if radar.minimum_body_distance_sigma <= 0:
        raise ValueError("minimum_body_distance_sigma must be positive")
    if radar.activation_score < 0 or radar.activation_score > 100:
        raise ValueError("activation_score must be in [0, 100]")

    structure = policy.structure
    if structure.target_quantity <= 0:
        raise ValueError("target_quantity must be positive")
    if not Decimal(0) < structure.short_delta_min < structure.short_delta_max <= Decimal(1):
        raise ValueError("short Delta interval is invalid")
    if structure.minimum_wing_width_usd <= 0 or (
        structure.maximum_wing_width_usd <= structure.minimum_wing_width_usd
    ):
        raise ValueError("wing width interval is invalid")

    underwriting = policy.underwriting
    if underwriting.minimum_combined_net_credit_usd <= 0:
        raise ValueError("minimum combined net credit must be positive")
    _fraction(
        underwriting.minimum_credit_to_max_side_payoff,
        "minimum_credit_to_max_side_payoff",
    )
    _fraction(
        underwriting.maximum_total_fee_fraction_of_credit,
        "maximum_total_fee_fraction_of_credit",
    )
    if underwriting.maximum_entry_boundary_loss_usd <= 0:
        raise ValueError("maximum entry-boundary loss must be positive")

    position = policy.position
    _fraction(position.take_profit_fraction_of_credit, "take_profit_fraction_of_credit")
    if position.take_profit_fraction_of_credit == 0:
        raise ValueError("take-profit fraction must be positive")
    if position.maximum_loss_multiple_of_credit <= 0:
        raise ValueError("maximum loss multiple must be positive")
    if not Decimal(0) < position.maximum_short_abs_delta <= Decimal(1):
        raise ValueError("maximum short Delta must be in (0, 1]")
    _fraction(position.maximum_adverse_move_fraction, "maximum_adverse_move_fraction")
    _fraction(position.maximum_rv_acceleration, "position maximum_rv_acceleration")
    if position.latest_short_risk_exit_minutes_to_expiry < session.delivery_twap_minutes_to_expiry:
        raise ValueError("short-risk exit cannot be later than the delivery TWAP boundary")
    if position.latest_short_risk_exit_minutes_to_expiry > (session.exit_only_minutes_to_expiry):
        raise ValueError("short-risk exit cannot precede the declared exit-only phase")

    shadow = policy.shadow
    if shadow.maximum_pair_receive_skew_ms > shadow.entry_acquisition_window_ms:
        raise ValueError("pair receive skew cannot exceed the entry-acquisition window")
    if shadow.maximum_pair_source_skew_ms > shadow.entry_acquisition_window_ms:
        raise ValueError("pair source skew cannot exceed the entry-acquisition window")
    if shadow.maximum_position_quote_age_ms > shadow.entry_acquisition_window_ms:
        raise ValueError("position quote age cannot exceed the entry-acquisition window")


def _fraction(value: Decimal, field_name: str) -> None:
    if not value.is_finite() or value < 0 or value > 1:
        raise ValueError(f"{field_name} must be in [0, 1]")


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


def _decimal(value: dict[str, Any], field: str) -> Decimal:
    member = value.get(field)
    if isinstance(member, bool) or member is None:
        raise ValueError(f"{field} must be a decimal-compatible value")
    parsed = Decimal(str(member))
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _bool(value: dict[str, Any], field: str) -> bool:
    member = value.get(field)
    if not isinstance(member, bool):
        raise ValueError(f"{field} must be boolean")
    return member
