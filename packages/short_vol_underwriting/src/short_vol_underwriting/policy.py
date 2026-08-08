from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from decimal import Decimal
from pathlib import Path

from options_domain import OptionProductSpec, product_for_identity
from short_vol_radar.policy import PolicyError as RadarPolicyError
from short_vol_radar.policy import RadarPolicy, load_policy_bytes

from short_vol_underwriting.identity import IDENTITY_PATTERN

UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MAX_INT64 = 9_223_372_036_854_775_807
FIXED_FEE_RATE = Decimal("0.0003")


class PolicyChainError(ValueError):
    """The immutable three-Policy chain is invalid or incompatible."""


@dataclass(frozen=True)
class UnderwritingPolicy:
    identity: str
    policy_semantic_name: str
    execution_model: str
    radar_policy_identity: str
    target_base_quantity_btc: Decimal
    clock_currentness_budget_ms: int
    platform_currentness_budget_ms: int
    component_book_snapshot_send_budget_ms: int
    component_book_snapshot_response_budget_ms: int
    maximum_component_pair_source_skew_ms: int
    maximum_component_pair_receive_skew_ms: int
    index_currentness_budget_ms: int
    option_ticker_currentness_budget_ms: int
    fee_role: str
    fee_schedule_source_url: str
    fee_schedule_retrieved_at_utc: str
    fee_schedule_effective_label: str
    fee_rate_index_fraction: Decimal
    path_risk_reserve_usdc: Decimal
    jump_risk_reserve_usdc: Decimal
    tail_risk_reserve_usdc: Decimal
    liquidity_cost_reserve_usdc: Decimal
    uncertainty_reserve_usdc: Decimal
    settlement_cost_reserve_usdc: Decimal
    maximum_underwriting_reserved_loss_usdc: Decimal
    minimum_net_entry_credit_usdc: Decimal
    minimum_net_credit_to_payoff_cap_fraction: Decimal
    maximum_entry_consumed_level_count: int

    @property
    def future_cost_reserve_usdc(self) -> Decimal:
        return (
            self.path_risk_reserve_usdc
            + self.jump_risk_reserve_usdc
            + self.tail_risk_reserve_usdc
            + self.liquidity_cost_reserve_usdc
            + self.uncertainty_reserve_usdc
            + self.settlement_cost_reserve_usdc
        )


@dataclass(frozen=True)
class PositionPolicy:
    identity: str
    policy_semantic_name: str
    execution_model: str
    underwriting_policy_identity: str
    target_base_quantity_btc: Decimal
    clock_currentness_budget_ms: int
    platform_currentness_budget_ms: int
    component_book_snapshot_send_budget_ms: int
    component_book_snapshot_response_budget_ms: int
    maximum_component_pair_source_skew_ms: int
    maximum_component_pair_receive_skew_ms: int
    index_currentness_budget_ms: int
    option_ticker_currentness_budget_ms: int
    fee_role: str
    fee_schedule_source_url: str
    fee_schedule_retrieved_at_utc: str
    fee_schedule_effective_label: str
    fee_rate_index_fraction: Decimal
    latest_exit_lead_ms: int
    maximum_projected_net_loss_usdc: Decimal
    maximum_absolute_short_delta: Decimal
    maximum_absolute_index_return_since_entry_fraction: Decimal
    maximum_absolute_index_return_since_prior_evaluation_fraction: Decimal
    maximum_short_mark_iv_increase_fraction: Decimal
    maximum_close_consumed_level_count: int
    minimum_take_profit_usdc: Decimal
    maximum_remaining_premium_fraction: Decimal


@dataclass(frozen=True)
class PolicyChain:
    radar: RadarPolicy
    underwriting: UnderwritingPolicy
    position: PositionPolicy

    @property
    def identities(self) -> tuple[str, str, str]:
        return (
            self.radar.identity,
            self.underwriting.identity,
            self.position.identity,
        )


def load_policy_chain(
    *,
    radar_path: Path,
    underwriting_path: Path,
    position_path: Path,
    radar_identity: str,
    underwriting_identity: str,
    position_identity: str,
) -> PolicyChain:
    _require_identity(radar_identity, "radar_identity")
    _require_identity(underwriting_identity, "underwriting_identity")
    _require_identity(position_identity, "position_identity")
    radar_bytes = _read_exact_bytes(radar_path)
    underwriting_bytes = _read_exact_bytes(underwriting_path)
    position_bytes = _read_exact_bytes(position_path)
    try:
        radar = load_policy_bytes(radar_bytes, radar_identity)
    except RadarPolicyError as exc:
        raise PolicyChainError(f"invalid Radar Policy: {exc}") from exc
    product = product_for_identity(radar.product_spec_identity)
    underwriting = _parse_underwriting(
        _load_exact_json(underwriting_bytes, underwriting_identity, "Underwriting Policy"),
        underwriting_identity,
        product=product,
    )
    position = _parse_position(
        _load_exact_json(position_bytes, position_identity, "Position Policy"),
        position_identity,
        product=product,
    )
    if underwriting.radar_policy_identity != radar.identity:
        raise PolicyChainError("Underwriting Policy Radar identity mismatch")
    if position.underwriting_policy_identity != underwriting.identity:
        raise PolicyChainError("Position Policy Underwriting identity mismatch")
    if underwriting.target_base_quantity_btc != radar.target_base_quantity_btc:
        raise PolicyChainError("Radar and Underwriting target quantity mismatch")
    if position.target_base_quantity_btc != underwriting.target_base_quantity_btc:
        raise PolicyChainError("Underwriting and Position target quantity mismatch")
    _validate_shared_policy_members(underwriting, position)
    return PolicyChain(radar=radar, underwriting=underwriting, position=position)


def _read_exact_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PolicyChainError(f"cannot read Policy: {path}") from exc


def _load_exact_json(exact_bytes: bytes, expected_identity: str, label: str) -> dict[str, object]:
    actual_identity = f"sha256:{hashlib.sha256(exact_bytes).hexdigest()}"
    if actual_identity != expected_identity:
        raise PolicyChainError(f"{label} digest mismatch")
    if exact_bytes.startswith(b"\xef\xbb\xbf"):
        raise PolicyChainError(f"{label} must not contain a UTF-8 BOM")
    try:
        text = exact_bytes.decode("utf-8")
        value = json.loads(
            text,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, PolicyChainError) as exc:
        raise PolicyChainError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyChainError(f"{label} must be one object")
    return value


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyChainError(f"duplicate Policy member: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise PolicyChainError(f"non-finite Policy number: {value}")


def _parse_underwriting(
    raw: dict[str, object],
    identity: str,
    *,
    product: OptionProductSpec,
) -> UnderwritingPolicy:
    raw = _product_policy_keys(
        raw,
        product=product,
        inverse_to_internal={
            "fee_rate_base_fraction": "fee_rate_index_fraction",
            "path_risk_reserve_usd": "path_risk_reserve_usdc",
            "jump_risk_reserve_usd": "jump_risk_reserve_usdc",
            "tail_risk_reserve_usd": "tail_risk_reserve_usdc",
            "liquidity_cost_reserve_usd": "liquidity_cost_reserve_usdc",
            "uncertainty_reserve_usd": "uncertainty_reserve_usdc",
            "settlement_cost_reserve_usd": "settlement_cost_reserve_usdc",
            "maximum_underwriting_reserved_loss_usd": ("maximum_underwriting_reserved_loss_usdc"),
            "minimum_net_entry_credit_usd": "minimum_net_entry_credit_usdc",
        },
        label="Underwriting Policy",
    )
    expected = {field.name for field in fields(UnderwritingPolicy)} - {"identity"}
    _require_exact_keys(raw, expected, "Underwriting Policy")
    policy = UnderwritingPolicy(
        identity=identity,
        policy_semantic_name=_exact_string(
            raw["policy_semantic_name"],
            "SHORT_VOL_PUBLIC_SHADOW_UNDERWRITING_POLICY",
            "policy_semantic_name",
        ),
        execution_model=_exact_string(
            raw["execution_model"],
            "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "execution_model",
        ),
        radar_policy_identity=_require_identity(
            raw["radar_policy_identity"], "radar_policy_identity"
        ),
        target_base_quantity_btc=_positive_decimal(
            raw["target_base_quantity_btc"], "target_base_quantity_btc"
        ),
        clock_currentness_budget_ms=_positive_ms(
            raw["clock_currentness_budget_ms"], "clock_currentness_budget_ms"
        ),
        platform_currentness_budget_ms=_positive_ms(
            raw["platform_currentness_budget_ms"], "platform_currentness_budget_ms"
        ),
        component_book_snapshot_send_budget_ms=_positive_ms(
            raw["component_book_snapshot_send_budget_ms"],
            "component_book_snapshot_send_budget_ms",
        ),
        component_book_snapshot_response_budget_ms=_positive_ms(
            raw["component_book_snapshot_response_budget_ms"],
            "component_book_snapshot_response_budget_ms",
        ),
        maximum_component_pair_source_skew_ms=_positive_ms(
            raw["maximum_component_pair_source_skew_ms"],
            "maximum_component_pair_source_skew_ms",
        ),
        maximum_component_pair_receive_skew_ms=_positive_ms(
            raw["maximum_component_pair_receive_skew_ms"],
            "maximum_component_pair_receive_skew_ms",
        ),
        index_currentness_budget_ms=_positive_ms(
            raw["index_currentness_budget_ms"], "index_currentness_budget_ms"
        ),
        option_ticker_currentness_budget_ms=_positive_ms(
            raw["option_ticker_currentness_budget_ms"], "option_ticker_currentness_budget_ms"
        ),
        fee_role=_exact_string(raw["fee_role"], "TAKER", "fee_role"),
        fee_schedule_source_url=_https_url(
            raw["fee_schedule_source_url"], "fee_schedule_source_url"
        ),
        fee_schedule_retrieved_at_utc=_utc_timestamp(
            raw["fee_schedule_retrieved_at_utc"], "fee_schedule_retrieved_at_utc"
        ),
        fee_schedule_effective_label=_bounded_string(
            raw["fee_schedule_effective_label"], "fee_schedule_effective_label"
        ),
        fee_rate_index_fraction=_exact_decimal(
            raw["fee_rate_index_fraction"], FIXED_FEE_RATE, "fee_rate_index_fraction"
        ),
        path_risk_reserve_usdc=_non_negative_decimal(
            raw["path_risk_reserve_usdc"], "path_risk_reserve_usdc"
        ),
        jump_risk_reserve_usdc=_non_negative_decimal(
            raw["jump_risk_reserve_usdc"], "jump_risk_reserve_usdc"
        ),
        tail_risk_reserve_usdc=_non_negative_decimal(
            raw["tail_risk_reserve_usdc"], "tail_risk_reserve_usdc"
        ),
        liquidity_cost_reserve_usdc=_non_negative_decimal(
            raw["liquidity_cost_reserve_usdc"], "liquidity_cost_reserve_usdc"
        ),
        uncertainty_reserve_usdc=_non_negative_decimal(
            raw["uncertainty_reserve_usdc"], "uncertainty_reserve_usdc"
        ),
        settlement_cost_reserve_usdc=_non_negative_decimal(
            raw["settlement_cost_reserve_usdc"], "settlement_cost_reserve_usdc"
        ),
        maximum_underwriting_reserved_loss_usdc=_positive_decimal(
            raw["maximum_underwriting_reserved_loss_usdc"],
            "maximum_underwriting_reserved_loss_usdc",
        ),
        minimum_net_entry_credit_usdc=_positive_decimal(
            raw["minimum_net_entry_credit_usdc"], "minimum_net_entry_credit_usdc"
        ),
        minimum_net_credit_to_payoff_cap_fraction=_open_unit_decimal(
            raw["minimum_net_credit_to_payoff_cap_fraction"],
            "minimum_net_credit_to_payoff_cap_fraction",
        ),
        maximum_entry_consumed_level_count=_level_count(
            raw["maximum_entry_consumed_level_count"], "maximum_entry_consumed_level_count"
        ),
    )
    return policy


def _parse_position(
    raw: dict[str, object],
    identity: str,
    *,
    product: OptionProductSpec,
) -> PositionPolicy:
    raw = _product_policy_keys(
        raw,
        product=product,
        inverse_to_internal={
            "fee_rate_base_fraction": "fee_rate_index_fraction",
            "maximum_projected_net_loss_usd": "maximum_projected_net_loss_usdc",
            "minimum_take_profit_usd": "minimum_take_profit_usdc",
        },
        label="Position Policy",
    )
    expected = {field.name for field in fields(PositionPolicy)} - {"identity"}
    _require_exact_keys(raw, expected, "Position Policy")
    return PositionPolicy(
        identity=identity,
        policy_semantic_name=_exact_string(
            raw["policy_semantic_name"],
            "SHORT_VOL_PUBLIC_SHADOW_POSITION_POLICY",
            "policy_semantic_name",
        ),
        execution_model=_exact_string(
            raw["execution_model"],
            "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "execution_model",
        ),
        underwriting_policy_identity=_require_identity(
            raw["underwriting_policy_identity"], "underwriting_policy_identity"
        ),
        target_base_quantity_btc=_positive_decimal(
            raw["target_base_quantity_btc"], "target_base_quantity_btc"
        ),
        clock_currentness_budget_ms=_positive_ms(
            raw["clock_currentness_budget_ms"], "clock_currentness_budget_ms"
        ),
        platform_currentness_budget_ms=_positive_ms(
            raw["platform_currentness_budget_ms"], "platform_currentness_budget_ms"
        ),
        component_book_snapshot_send_budget_ms=_positive_ms(
            raw["component_book_snapshot_send_budget_ms"],
            "component_book_snapshot_send_budget_ms",
        ),
        component_book_snapshot_response_budget_ms=_positive_ms(
            raw["component_book_snapshot_response_budget_ms"],
            "component_book_snapshot_response_budget_ms",
        ),
        maximum_component_pair_source_skew_ms=_positive_ms(
            raw["maximum_component_pair_source_skew_ms"],
            "maximum_component_pair_source_skew_ms",
        ),
        maximum_component_pair_receive_skew_ms=_positive_ms(
            raw["maximum_component_pair_receive_skew_ms"],
            "maximum_component_pair_receive_skew_ms",
        ),
        index_currentness_budget_ms=_positive_ms(
            raw["index_currentness_budget_ms"], "index_currentness_budget_ms"
        ),
        option_ticker_currentness_budget_ms=_positive_ms(
            raw["option_ticker_currentness_budget_ms"], "option_ticker_currentness_budget_ms"
        ),
        fee_role=_exact_string(raw["fee_role"], "TAKER", "fee_role"),
        fee_schedule_source_url=_https_url(
            raw["fee_schedule_source_url"], "fee_schedule_source_url"
        ),
        fee_schedule_retrieved_at_utc=_utc_timestamp(
            raw["fee_schedule_retrieved_at_utc"], "fee_schedule_retrieved_at_utc"
        ),
        fee_schedule_effective_label=_bounded_string(
            raw["fee_schedule_effective_label"], "fee_schedule_effective_label"
        ),
        fee_rate_index_fraction=_exact_decimal(
            raw["fee_rate_index_fraction"], FIXED_FEE_RATE, "fee_rate_index_fraction"
        ),
        latest_exit_lead_ms=_exact_integer(
            raw["latest_exit_lead_ms"], 1_800_000, "latest_exit_lead_ms"
        ),
        maximum_projected_net_loss_usdc=_positive_decimal(
            raw["maximum_projected_net_loss_usdc"], "maximum_projected_net_loss_usdc"
        ),
        maximum_absolute_short_delta=_open_unit_decimal(
            raw["maximum_absolute_short_delta"], "maximum_absolute_short_delta"
        ),
        maximum_absolute_index_return_since_entry_fraction=_positive_decimal(
            raw["maximum_absolute_index_return_since_entry_fraction"],
            "maximum_absolute_index_return_since_entry_fraction",
        ),
        maximum_absolute_index_return_since_prior_evaluation_fraction=_positive_decimal(
            raw["maximum_absolute_index_return_since_prior_evaluation_fraction"],
            "maximum_absolute_index_return_since_prior_evaluation_fraction",
        ),
        maximum_short_mark_iv_increase_fraction=_positive_decimal(
            raw["maximum_short_mark_iv_increase_fraction"],
            "maximum_short_mark_iv_increase_fraction",
        ),
        maximum_close_consumed_level_count=_level_count(
            raw["maximum_close_consumed_level_count"], "maximum_close_consumed_level_count"
        ),
        minimum_take_profit_usdc=_non_negative_decimal(
            raw["minimum_take_profit_usdc"], "minimum_take_profit_usdc"
        ),
        maximum_remaining_premium_fraction=_closed_unit_decimal(
            raw["maximum_remaining_premium_fraction"], "maximum_remaining_premium_fraction"
        ),
    )


def _validate_shared_policy_members(
    underwriting: UnderwritingPolicy, position: PositionPolicy
) -> None:
    shared = (
        "execution_model",
        "target_base_quantity_btc",
        "clock_currentness_budget_ms",
        "platform_currentness_budget_ms",
        "component_book_snapshot_send_budget_ms",
        "component_book_snapshot_response_budget_ms",
        "maximum_component_pair_source_skew_ms",
        "maximum_component_pair_receive_skew_ms",
        "index_currentness_budget_ms",
        "option_ticker_currentness_budget_ms",
        "fee_role",
        "fee_schedule_source_url",
        "fee_schedule_retrieved_at_utc",
        "fee_schedule_effective_label",
        "fee_rate_index_fraction",
    )
    for field in shared:
        if getattr(underwriting, field) != getattr(position, field):
            raise PolicyChainError(f"Policy compatibility mismatch: {field}")


def _product_policy_keys(
    raw: dict[str, object],
    *,
    product: OptionProductSpec,
    inverse_to_internal: dict[str, str],
    label: str,
) -> dict[str, object]:
    if not product.is_inverse:
        return raw
    forbidden_internal = set(inverse_to_internal.values()) & set(raw)
    if forbidden_internal:
        raise PolicyChainError(f"{label} uses Linear-only unit keys: {sorted(forbidden_internal)}")
    normalized = {inverse_to_internal.get(key, key): value for key, value in raw.items()}
    if len(normalized) != len(raw):
        raise PolicyChainError(f"{label} product-unit keys collide")
    return normalized


def _require_exact_keys(raw: dict[str, object], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        missing = sorted(expected - set(raw))
        unknown = sorted(set(raw) - expected)
        raise PolicyChainError(f"{label} requires exact keys; missing={missing}, unknown={unknown}")


def _number(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise PolicyChainError(f"{field} must be a finite JSON number")
    return value


def _integer(value: object, field: str) -> int:
    number = _number(value, field)
    if number != number.to_integral_value():
        raise PolicyChainError(f"{field} must be a JSON integer")
    return int(number)


def _positive_ms(value: object, field: str) -> int:
    number = _integer(value, field)
    if number < 1 or number > MAX_INT64:
        raise PolicyChainError(f"{field} must be in [1, 9223372036854775807]")
    return number


def _level_count(value: object, field: str) -> int:
    number = _integer(value, field)
    if number < 1 or number > 10_000:
        raise PolicyChainError(f"{field} must be in [1, 10000]")
    return number


def _positive_decimal(value: object, field: str) -> Decimal:
    number = _number(value, field)
    if number <= 0:
        raise PolicyChainError(f"{field} must be positive")
    return number


def _non_negative_decimal(value: object, field: str) -> Decimal:
    number = _number(value, field)
    if number < 0:
        raise PolicyChainError(f"{field} must be non-negative")
    return number


def _open_unit_decimal(value: object, field: str) -> Decimal:
    number = _number(value, field)
    if number <= 0 or number >= 1:
        raise PolicyChainError(f"{field} must be strictly between zero and one")
    return number


def _closed_unit_decimal(value: object, field: str) -> Decimal:
    number = _number(value, field)
    if number < 0 or number > 1:
        raise PolicyChainError(f"{field} must be in [0, 1]")
    return number


def _exact_decimal(value: object, expected: Decimal, field: str) -> Decimal:
    number = _number(value, field)
    if number != expected:
        raise PolicyChainError(f"{field} must be exactly {expected}")
    return number


def _exact_integer(value: object, expected: int, field: str) -> int:
    number = _integer(value, field)
    if number != expected:
        raise PolicyChainError(f"{field} must be exactly {expected}")
    return number


def _exact_string(value: object, expected: str, field: str) -> str:
    if value != expected:
        raise PolicyChainError(f"{field} must be exactly {expected}")
    return expected


def _bounded_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise PolicyChainError(f"{field} must be a non-empty string of at most 128 scalars")
    return value


def _https_url(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://") or len(value) <= 8:
        raise PolicyChainError(f"{field} must be a non-empty HTTPS URL")
    return value


def _utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise PolicyChainError(f"{field} must be YYYY-MM-DDTHH:MM:SSZ")
    return value


def _require_identity(value: object, field: str) -> str:
    if not isinstance(value, str) or IDENTITY_PATTERN.fullmatch(value) is None:
        raise PolicyChainError(f"{field} must be sha256:<64 lowercase hex>")
    return value
